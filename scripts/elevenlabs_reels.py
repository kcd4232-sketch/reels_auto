"""Clone a supplied voice and create narration with timed subtitles from 대본.md."""
from __future__ import annotations

import argparse
import base64
from contextlib import ExitStack
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

from dotenv import load_dotenv
from elevenlabs import ElevenLabs

AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".flac"}


def save_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def probe_seconds(path: Path) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, check=True,
    )
    return float(result.stdout.strip())


def get_client(root: Path) -> ElevenLabs:
    load_dotenv(root / ".env.local", override=False)
    if not os.environ.get("ELEVENLABS_API_KEY"):
        raise ValueError("ElevenLabs 키가 없습니다. 이 폴더에서 onboard init을 실행하세요.")
    return ElevenLabs(api_key=os.environ["ELEVENLABS_API_KEY"])


def unique_samples(root: Path) -> tuple[list[Path], list[str]]:
    folder = root / "음성"
    if not folder.is_dir():
        raise ValueError(f"음성 폴더가 없습니다: {folder}")
    unique: dict[str, Path] = {}
    for path in sorted(folder.iterdir()):
        if path.is_file() and path.suffix.lower() in AUDIO_EXTENSIONS:
            unique.setdefault(sha256(path), path)
    if not unique:
        raise ValueError(f"음성 파일이 없습니다: {folder}")
    paths = list(unique.values())
    lengths = [probe_seconds(path) for path in paths]
    if any(t < 5 for t in lengths) or sum(lengths) < 10:
        raise ValueError("복제 샘플은 파일별 5초 이상, 합계 10초 이상이어야 합니다.")
    return paths, list(unique)


def api_error(exc: Exception) -> str:
    body = getattr(exc, "body", None)
    detail = body.get("detail", body) if isinstance(body, dict) else {}
    if isinstance(detail, dict):
        code = detail.get("status", "")
        message = str(detail.get("message", ""))[:240]
        return f"{type(exc).__name__}, HTTP {getattr(exc, 'status_code', None)}, {code}: {message}"
    return f"{type(exc).__name__}, HTTP {getattr(exc, 'status_code', None)}"


def clone(root: Path, name: str, new_clone: bool) -> None:
    paths, hashes = unique_samples(root)
    voice_path = root / "elevenlabs_voice.json"
    if voice_path.exists():
        previous = json.loads(voice_path.read_text(encoding="utf-8"))
        if previous.get("sample_hashes") == hashes and not new_clone:
            print(f"기존 목소리 재사용: {previous['name']} ({previous['voice_id']})")
            return
        if not new_clone:
            raise ValueError("샘플이 바뀌었습니다. 별도 목소리를 만들려면 --new-clone을 지정하세요.")
    try:
        with ExitStack() as stack:
            streams = [stack.enter_context(path.open("rb")) for path in paths]
            result = get_client(root).voices.ivc.create(
                name=name, files=streams, labels={}, remove_background_noise=False,
                description="Narration voice for the owner's instar_reels project.",
            )
    except Exception as exc:
        raise RuntimeError(f"목소리 등록 실패: {api_error(exc)}") from None
    if voice_path.exists():
        backup = voice_path.with_name(
            f"elevenlabs_voice.previous-{datetime.now():%Y%m%d-%H%M%S}.json"
        )
        backup.write_bytes(voice_path.read_bytes())
    save_json(voice_path, {
        "voice_id": result.voice_id, "name": name,
        "sample_files": [path.name for path in paths],
        "sample_hashes": hashes,
        "requires_verification": bool(result.requires_verification),
    })
    print(f"목소리 등록 완료: {result.voice_id}, 고유 샘플 {len(paths)}개")
    if result.requires_verification:
        print("ElevenLabs에서 추가 목소리 인증이 필요합니다.")


def parse_script(path: Path) -> tuple[str, list[dict]]:
    if not path.is_file():
        raise ValueError(f"대본 파일이 없습니다: {path}")
    sections: list[dict] = []
    title = ""
    hook = ""
    visual = ""
    lines: list[str] = []
    in_code = False

    def flush() -> None:
        nonlocal lines, hook, visual
        spoken = " ".join(lines).strip()
        if spoken:
            sections.append({"title": title, "hook": hook, "visual": visual,
                             "text": spoken})
        lines = []
        hook = ""
        visual = ""

    source = path.read_text(encoding="utf-8-sig")
    source = re.sub(r"<!--.*?(?:-->|$)", "", source, flags=re.DOTALL)
    for raw in source.splitlines():
        line = raw.strip()
        if line.startswith(chr(96) * 3):
            in_code = not in_code
            continue
        if in_code or not line or line.startswith(("<!--", "|", "---")):
            continue
        if line.startswith(">"):
            marked_hook = re.match(r"^>\s*(?:훅|강조 자막|상단 훅)\s*[:：]\s*(.+)$", line)
            if marked_hook:
                hook = marked_hook.group(1).strip()
            continue
        heading = re.match(r"^#{2,6}\s+(.+)$", line)
        if heading:
            flush()
            title = re.sub(r"^\d+\s*[~–-]\s*\d+\s*초\s*\|\s*", "",
                           heading.group(1).strip())
            continue
        if line.startswith("#"):
            continue
        marked = re.match(
            r"^[-*+]\s+(?:\*\*)?(화면|내레이션|강조 자막|훅)(?:\*\*)?\s*[—–:-]\s*(.+)$",
            line,
        )
        if marked:
            kind, value = marked.groups()
            if kind in {"강조 자막", "훅"}:
                hook = value.strip()
            elif kind == "화면":
                visual = value.strip()
            elif kind == "내레이션":
                lines.append(value.strip().strip("“”\""))
            continue
        line = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", line)
        line = re.sub(r"\[[^\]]*\]", " ", line)
        line = re.sub(r"^[-*+]\s+|^\d+[.)]\s+", "", line)
        line = re.sub(r"\s+", " ", line.replace("**", "").replace("__", "")).strip()
        if line:
            lines.append(line)
    flush()
    if not sections:
        raise ValueError("대본에 읽을 문장이 없습니다. 제목과 [화면 지시] 외에 문장을 적으세요.")
    pos = 0
    for section in sections:
        section["char_start"] = pos
        pos += len(section["text"])
        section["char_end"] = pos
        pos += 1
    return " ".join(section["text"] for section in sections), sections


def character_map(text: str, alignment: object) -> list[int | None]:
    chars = list(alignment.characters)
    if not (len(chars) == len(alignment.character_start_times_seconds)
            == len(alignment.character_end_times_seconds)):
        raise ValueError("글자별 발화 시각의 길이가 맞지 않습니다.")
    if "".join(chars) == text:
        return list(range(len(text)))
    spoken = [(i, char.lower()) for i, char in enumerate(chars) if char.isalnum()]
    expected = [(i, char.lower()) for i, char in enumerate(text) if char.isalnum()]
    if [char for _, char in spoken] != [char for _, char in expected]:
        raise ValueError("발화 시각의 글자가 대본과 달라 자막을 정확히 맞출 수 없습니다.")
    mapping: list[int | None] = [None] * len(text)
    for (audio_i, _), (text_i, _) in zip(spoken, expected):
        mapping[text_i] = audio_i
    return mapping


def timed_words(text: str, sections: list[dict], alignment: object) -> list[dict]:
    mapping = character_map(text, alignment)
    starts = alignment.character_start_times_seconds
    ends = alignment.character_end_times_seconds
    words: list[dict] = []
    for match in re.finditer(r"\S+", text):
        indices = [mapping[i] for i in range(match.start(), match.end()) if mapping[i] is not None]
        if not indices:
            if words:
                words[-1]["text"] += " " + match.group()
            continue
        section = next(
            (i for i, row in enumerate(sections)
             if row["char_start"] <= match.start() < row["char_end"]), 0
        )
        start = max(0.0, min(float(starts[i]) for i in indices))
        end = max(float(ends[i]) for i in indices)
        words.append({
            "start": start, "end": max(end, start + 0.05),
            "text": match.group(), "char_start": match.start(),
            "char_end": match.end(), "section": section,
        })
    if not words:
        raise ValueError("발화 시각에서 단어를 찾지 못했습니다.")
    if any(b["start"] + 0.01 < a["start"] for a, b in zip(words, words[1:])):
        raise ValueError("발화 시각이 역순입니다.")
    return words


def captions(words: list[dict], text: str) -> list[dict]:
    groups: list[list[dict]] = []
    current: list[dict] = []
    for word in words:
        if current:
            proposed = text[current[0]["char_start"]:word["char_end"]]
            last = current[-1]
            if (word["section"] != last["section"]
                    or last["text"].endswith((".", "?", "!", "。", "！", "？"))
                    or len(proposed) > 22 or word["end"] - current[0]["start"] > 3.3):
                groups.append(current)
                current = []
        current.append(word)
    if current:
        groups.append(current)
    cues = [
        {
            "start": max(0.0, group[0]["start"] - 0.06),
            "end": group[-1]["end"] + 0.12,
            "text": text[group[0]["char_start"]:group[-1]["char_end"]].strip(),
        }
        for group in groups
    ]
    for cue, following in zip(cues, cues[1:]):
        cue["end"] = max(cue["start"] + 0.05,
                         min(cue["end"], following["start"] - 0.03))
    return cues


def srt_time(seconds: float) -> str:
    millis = max(0, round(seconds * 1000))
    hour, millis = divmod(millis, 3600000)
    minute, millis = divmod(millis, 60000)
    second, millis = divmod(millis, 1000)
    return f"{hour:02d}:{minute:02d}:{second:02d},{millis:03d}"


def generate(root: Path, script: Path, model: str, regenerate: bool) -> Path:
    voice_path = root / "elevenlabs_voice.json"
    if not voice_path.is_file():
        raise ValueError("등록된 목소리가 없습니다. 먼저 clone을 실행하세요.")
    voice = json.loads(voice_path.read_text(encoding="utf-8"))
    if voice.get("requires_verification"):
        raise ValueError("ElevenLabs에서 목소리 인증을 완료한 뒤 다시 실행하세요.")
    text, sections = parse_script(script)
    key = hashlib.sha256(
        (voice["voice_id"] + "\n" + model + "\n" + text).encode("utf-8")
    ).hexdigest()[:12]
    base = root / "편집" / "elevenlabs" / key
    if not regenerate:
        candidates = [base]
        candidates.extend(sorted(
            base.parent.glob(base.name + "-*"),
            key=lambda item: item.stat().st_mtime_ns, reverse=True,
        ))
        for candidate in candidates:
            manifest_path = candidate / "manifest.json"
            if not manifest_path.is_file():
                continue
            cached = json.loads(manifest_path.read_text(encoding="utf-8"))
            if (cached.get("text") != text
                    or cached.get("voice_id") != voice["voice_id"]
                    or cached.get("model") != model
                    or [row.get("text") for row in cached.get("sections", [])]
                    != [section["text"] for section in sections]):
                continue
            # The audio cache belongs to the spoken text. A different script may
            # use the same words with a different hook or shot plan; render() gets
            # those per-job details through script_override instead of changing
            # this shared manifest.
            print(f"동일한 대본의 기존 음성을 재사용합니다: {candidate}")
            return candidate
    out = base
    if out.exists():
        out = base.with_name(base.name + "-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
    out.mkdir(parents=True, exist_ok=False)
    try:
        response = get_client(root).text_to_speech.convert_with_timestamps(
            voice["voice_id"], text=text, model_id=model, language_code="ko",
            output_format="mp3_44100_128",
        )
    except Exception as exc:
        raise RuntimeError(f"음성 생성 실패: {api_error(exc)}") from None
    if response.alignment is None:
        raise ValueError("ElevenLabs가 글자별 발화 시각을 반환하지 않았습니다.")
    words = timed_words(text, sections, response.alignment)
    audio = out / "narration.mp3"
    audio.write_bytes(base64.b64decode(response.audio_base_64, validate=True))
    duration = probe_seconds(audio)
    cues = captions(words, text)
    for cue in cues:
        cue["end"] = min(cue["end"], duration)
    cues = [cue for cue in cues if cue["start"] < cue["end"]]
    section_rows = []
    for index, section in enumerate(sections):
        own = [word for word in words if word["section"] == index]
        if not own:
            raise ValueError(f"대본 구간의 발화 시각이 없습니다: {section['title']}")
        section_rows.append({
            "title": section["title"], "hook": section["hook"],
            "visual": section["visual"],
            "text": section["text"],
            "start": own[0]["start"], "end": min(own[-1]["end"], duration),
        })
    save_json(out / "words.json", [
        {"start": w["start"], "end": w["end"], "word": w["text"]} for w in words
    ])
    save_json(out / "cues.json", cues)
    srt = "\n".join(
        f"{i}\n{srt_time(cue['start'])} --> {srt_time(cue['end'])}\n{cue['text']}\n"
        for i, cue in enumerate(cues, 1)
    )
    (out / "captions.srt").write_text(srt, encoding="utf-8-sig")
    save_json(out / "manifest.json", {
        "source_script": str(script.resolve()), "script_sha256": sha256(script),
        "voice_id": voice["voice_id"], "model": model,
        "duration": duration, "text": text,
        "sections": section_rows, "caption_count": len(cues),
    })
    print(f"나레이션: {audio}")
    print(f"시간 자막 {len(cues)}개: {out / 'captions.srt'}")
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="목소리 복제와 대본 기반 음성·자막 생성")
    parser.add_argument("--work-root", type=Path, default=Path.cwd())
    sub = parser.add_subparsers(dest="command", required=True)
    clone_cmd = sub.add_parser("clone")
    clone_cmd.add_argument("--name", default="instar_reels narration")
    clone_cmd.add_argument("--new-clone", action="store_true")
    gen_cmd = sub.add_parser("generate")
    gen_cmd.add_argument("--script", type=Path)
    gen_cmd.add_argument("--model", default="eleven_v4")
    gen_cmd.add_argument("--regenerate", action="store_true")
    args = parser.parse_args()
    root = args.work_root.resolve()
    try:
        if args.command == "clone":
            clone(root, args.name, args.new_clone)
        else:
            script = (args.script or root / "대본" / "대본.md").resolve()
            generate(root, script, args.model, args.regenerate)
    except (ValueError, RuntimeError, OSError, subprocess.CalledProcessError) as exc:
        print(f"[오류] {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
