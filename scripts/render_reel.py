"""Assemble source clips, cloned narration and timed captions into a vertical MP4."""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Callable
import unicodedata
import xml.etree.ElementTree as ElementTree

from elevenlabs_reels import parse_script, probe_seconds, sha256

VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi"}
DEFAULT_VOICE_SPEED = 1.125  # Previous 1.25x playback slowed to 90%.
OUTRO_IMAGE_EXTENSIONS = {".svg", ".png", ".jpg", ".jpeg", ".webp"}


def call(command: list[str], cwd: Path | None = None) -> None:
    result = subprocess.run(command, cwd=cwd, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(
            f"명령 실패 ({result.returncode}): {' '.join(command[:5])}\n"
            + result.stderr[-1800:]
        )


def call_with_progress(command: list[str], cwd: Path, duration: float,
                       notify: Callable[[float], None]) -> None:
    """Read FFmpeg's encoded timestamp so the UI shows actual final-pass progress."""
    process = subprocess.Popen(command, cwd=cwd, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, text=True,
                               encoding="utf-8", errors="replace")
    last = -1
    tail = ""
    assert process.stdout is not None
    for line in process.stdout:
        tail = (tail + line)[-1800:]
        if line.startswith(("out_time_us=", "out_time_ms=")):
            try:
                elapsed = int(line.split("=", 1)[1]) / 1_000_000
            except ValueError:
                continue
            percent = int(100 * min(1.0, elapsed / max(.01, duration)))
            if percent > last:
                notify(percent / 100)
                last = percent
    if process.wait():
        raise RuntimeError("영상 최종 합성 실패:\n" + tail)


def read_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def choose_outro_image(project_root: Path, supplied: Path | None) -> Path | None:
    if supplied is not None:
        if not supplied.is_file() or supplied.suffix.lower() not in OUTRO_IMAGE_EXTENSIONS:
            raise ValueError("엔딩 이미지는 SVG, PNG, JPG 또는 WEBP 파일이어야 합니다.")
        return supplied
    folder = project_root / "로고"
    if not folder.is_dir():
        return None
    choices = sorted(path for path in folder.iterdir()
                     if path.is_file() and path.suffix.lower() in OUTRO_IMAGE_EXTENSIONS)
    return choices[0] if choices else None


def safe_svg_bytes(path: Path) -> bytes:
    """Accept self-contained artwork; do not let an uploaded SVG fetch resources."""
    source = path.read_bytes()
    if len(source) > 2 * 1024 * 1024:
        raise ValueError("SVG 파일은 2MB 이하로 첨부하세요.")
    lower = source.lower()
    if any(marker in lower for marker in
           (b"<!doctype", b"<!entity", b"<?xml-stylesheet", b"@import", b"@font-face")):
        raise ValueError("외부 참조가 있는 SVG는 사용할 수 없습니다.")
    try:
        root = ElementTree.fromstring(source)
    except ElementTree.ParseError as exc:
        raise ValueError(f"SVG 형식이 올바르지 않습니다: {exc}") from exc
    if root.tag.rsplit("}", 1)[-1].lower() != "svg":
        raise ValueError("SVG 루트 요소가 없습니다.")
    forbidden = {"script", "foreignobject", "image", "feimage",
                 "iframe", "object", "embed"}
    for node in root.iter():
        tag = node.tag.rsplit("}", 1)[-1].lower()
        if tag in forbidden:
            raise ValueError(f"SVG에 허용되지 않는 요소가 있습니다: {tag}")
        fields = list(node.attrib.items())
        if node.text:
            fields.append(("text", node.text))
        for key, value in fields:
            name = key.rsplit("}", 1)[-1].lower()
            value = value.strip()
            if name.startswith("on"):
                raise ValueError("SVG의 실행 코드는 사용할 수 없습니다.")
            if name == "href" and not value.startswith("#"):
                raise ValueError("SVG의 외부 파일 참조는 사용할 수 없습니다.")
            for url in re.findall(r"url\(([^)]+)\)", value, flags=re.IGNORECASE):
                if not url.strip().strip("'\"").startswith("#"):
                    raise ValueError("SVG의 외부 URL은 사용할 수 없습니다.")
    return source


def browser_binary() -> str | None:
    candidates = [
        shutil.which("chrome"), shutil.which("msedge"),
        shutil.which("chromium"), shutil.which("chromium-browser"),
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    ]
    return next((str(path) for path in candidates if path and Path(path).is_file()), None)


def make_outro_card(asset: Path, output: Path, width: int, height: int) -> Path:
    """Rasterize attached artwork on a contained black end card."""
    card = output / "outro_card.png"
    if asset.suffix.lower() == ".svg":
        svg = safe_svg_bytes(asset)
        browser = browser_binary()
        if not browser:
            raise ValueError("SVG 변환에 Chrome 또는 Edge가 필요합니다.")
        encoded = base64.b64encode(svg).decode("ascii")
        html = output / "outro_svg_preview.html"
        html.write_text(
            '<!doctype html><meta charset="utf-8">'
            '<meta http-equiv="Content-Security-Policy" '
            'content="default-src \'none\'; img-src data:; '
            'style-src \'unsafe-inline\'"><style>'
            'html,body{margin:0;width:100%;height:100%;overflow:hidden;background:#000}'
            'img{position:absolute;left:50%;top:45.5%;transform:translate(-50%,-50%);'
            'max-width:72vw;max-height:18vh;object-fit:contain}</style>'
            f'<img src="data:image/svg+xml;base64,{encoded}">',
            encoding="utf-8",
        )
        with tempfile.TemporaryDirectory(prefix="reels-svg-",
                                         ignore_cleanup_errors=True) as profile:
            command = [
                browser, "--headless=new", "--disable-gpu", "--no-first-run",
                "--no-default-browser-check", "--hide-scrollbars",
                "--disable-extensions", "--disable-background-networking",
                "--force-device-scale-factor=1", f"--user-data-dir={profile}",
                f"--window-size={width},{height}", f"--screenshot={card}",
                html.resolve().as_uri(),
            ]
            result = subprocess.run(command, capture_output=True,
                                    timeout=30)
            for _ in range(20):
                if card.is_file():
                    break
                time.sleep(.1)
            if result.returncode or not card.is_file():
                raise RuntimeError("SVG 엔딩 이미지를 PNG로 변환하지 못했습니다.")
    else:
        call([
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
            "-f", "lavfi", "-i", f"color=c=black:s={width}x{height}:r=1:d=1",
            "-i", str(asset),
            "-filter_complex",
            (f"[1:v]scale={round(width * .72)}:{round(height * .18)}:"
             "force_original_aspect_ratio=decrease[logo];"
             f"[0:v][logo]overlay=x=(W-w)/2:y=(H*.455-h/2):shortest=1:"
             "format=auto,format=rgb24[v]"),
            "-map", "[v]", "-frames:v", "1", str(card),
        ])
    dims = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=width,height",
         "-of", "csv=p=0:s=x", str(card)],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    if dims != f"{width}x{height}":
        raise RuntimeError(f"엔딩 이미지 크기가 잘못되었습니다: {dims}")
    return card


def script_metadata(manifest: dict, script: Path | None) -> dict:
    if script is None:
        return manifest
    text, parsed = parse_script(script)
    if (text != manifest["text"] or len(parsed) != len(manifest["sections"])
            or [row["text"] for row in parsed]
            != [row["text"] for row in manifest["sections"]]):
        raise ValueError("대본 내용이 저장된 나레이션과 다릅니다. 음성을 먼저 생성하세요.")
    return {**manifest, "sections": [
        {**row, "title": source["title"], "hook": source["hook"],
         "visual": source["visual"]}
        for row, source in zip(manifest["sections"], parsed)
    ]}


def latest_run(root: Path) -> Path:
    folder = root / "편집" / "elevenlabs"
    choices = [path for path in folder.iterdir()
               if path.is_dir() and (path / "manifest.json").is_file()] if folder.is_dir() else []
    if not choices:
        raise ValueError("생성된 나레이션이 없습니다. 먼저 elevenlabs_reels.py generate를 실행하세요.")
    return max(choices, key=lambda path: (path / "manifest.json").stat().st_mtime_ns)


def source_clips(root: Path) -> list[Path]:
    folder = root / "원본"
    clips = sorted(
        [path for path in folder.iterdir()
         if path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS],
        key=lambda path: (
            int(re.match(r"^(\d+)", path.stem).group(1))
            if re.match(r"^(\d+)", path.stem) else 9999,
            path.name.lower(),
        ),
    ) if folder.is_dir() else []
    if not clips:
        raise ValueError(f"원본 영상이 없습니다: {folder}")
    return clips


def cut_points(total: float, sections: list[dict], clips: list[Path],
               cues: list[dict]) -> tuple[list[float], str]:
    if len(sections) == len(clips) and len(clips) > 1 and all(s["title"] for s in sections):
        points = [0.0] + [float(s["start"]) for s in sections[1:]] + [total]
        mode = "대본 ## 제목 순서"
    else:
        lengths = [probe_seconds(path) for path in clips]
        cumulative = 0.0
        points = [0.0]
        gaps = [float(cue["end"]) for cue in cues[:-1]]
        for length in lengths[:-1]:
            cumulative += length
            ideal = total * cumulative / sum(lengths)
            near = [value for value in gaps if abs(value - ideal) <= 1.0]
            points.append(min(near, key=lambda value: abs(value - ideal)) if near else ideal)
        points.append(total)
        mode = "영상 길이 비율 + 가까운 자막 경계"
    if any(b - a < 0.25 for a, b in zip(points, points[1:])):
        raise ValueError("대본 구간이 너무 짧아 영상 컷을 배치할 수 없습니다.")
    return points, mode


def storyboard_cuts(sections: list[dict], available: list[Path],
                    total: float) -> tuple[list[Path], list[float]] | None:
    """Follow explicit '클립 (n)' directions when every section can be mapped."""
    by_number = {}
    for path in available:
        match = re.search(r"\((\d+)\)", path.stem)
        if match:
            by_number[match.group(1)] = path
    references = [
        re.findall(r"클립\s*\((\d+)\)", str(section.get("visual", "")))
        for section in sections
    ]
    if not references or any(not refs or any(ref not in by_number for ref in refs)
                             for refs in references):
        return None
    ordered: list[Path] = []
    points = [0.0]
    for index, refs in enumerate(references):
        start = points[-1]
        end = float(sections[index + 1]["start"]) if index + 1 < len(sections) else total
        if end - start < .25 * len(refs):
            return None
        for part, ref in enumerate(refs, 1):
            ordered.append(by_number[ref])
            points.append(start + (end - start) * part / len(refs))
    return ordered, points


def ass_time(seconds: float) -> str:
    centi = max(0, round(seconds * 100))
    hour, centi = divmod(centi, 360000)
    minute, centi = divmod(centi, 6000)
    sec, centi = divmod(centi, 100)
    return f"{hour}:{minute:02d}:{sec:02d}.{centi:02d}"


def ass_escape(value: str) -> str:
    return value.replace("\\", r"\\").replace("{", r"\{").replace("}", r"\}").replace("\n", r"\N")


def ass_color(value: str) -> str:
    color = value.lstrip("#")
    if not re.fullmatch(r"[0-9A-Fa-f]{6}", color):
        raise ValueError(f"잘못된 자막 색상: {value}")
    return f"&H00{color[4:6]}{color[2:4]}{color[0:2]}".upper()


def retime_words(words: list[dict], speed: float, lead: float = 0.10) -> list[dict]:
    return [{**row, "start": lead + float(row["start"]) / speed,
             "end": lead + float(row["end"]) / speed} for row in words]


def visual_units(value: str) -> float:
    return sum(1.0 if unicodedata.east_asian_width(char) in "WF"
               else .55 if char.isalnum() else .40 for char in value)


def concise_hook(section: dict, limit: float) -> str:
    explicit = str(section.get("hook", "")).strip()
    if explicit:
        candidate = explicit
    else:
        text = str(section.get("text", "")).strip()
        sentences = [piece.strip() for piece in re.split(r"(?<=[.!?])\s+", text)
                     if piece.strip()]
        candidate = next((piece for piece in sentences
                          if not piece.startswith("안녕하세요")), text)
        if visual_units(candidate) > limit and "," in candidate:
            clauses = [part.strip() for part in candidate.split(",") if part.strip()]
            fitting = [part for part in clauses if 6 <= visual_units(part) <= limit]
            if fitting:
                candidate = fitting[-1]
    candidate = re.sub(r"\s+", " ", candidate.strip(" “ ”\""))
    if visual_units(candidate) <= limit:
        return candidate
    shortened: list[str] = []
    for word in candidate.split():
        next_text = " ".join(shortened + [word])
        if visual_units(next_text + "…") > limit:
            break
        shortened.append(word)
    if shortened:
        return " ".join(shortened).rstrip(",. ") + "…"
    return candidate[:max(1, int(limit))] + "…"


def split_hook(value: str, first_limit: float, second_limit: float) -> tuple[str, str]:
    if visual_units(value) <= first_limit:
        return value, ""
    words = value.split()
    candidates = []
    for index in range(1, len(words)):
        first, second = " ".join(words[:index]), " ".join(words[index:])
        if visual_units(first) <= first_limit and visual_units(second) <= second_limit:
            score = abs(visual_units(first) - visual_units(second))
            if visual_units(second) < 4:
                score += 6
            candidates.append((score, first, second))
    if candidates:
        _, first, second = min(candidates)
        return first, second
    split_at = max(1, int(first_limit))
    return value[:split_at].rstrip(), value[split_at:].lstrip()


def headline_cards(sections: list[dict], cues: list[dict],
                   points: list[float], total: float,
                   width: int, style: dict) -> list[dict]:
    if not sections:
        return []
    headline = style["headline"]
    primary_size = round(width * .073 * headline["primary_scale"])
    second_size = round(primary_size * headline["continuation_scale"])
    first_limit = width * headline["max_width_ratio"] / (primary_size * .92)
    second_limit = width * headline["max_width_ratio"] / (second_size * .92)
    boundaries = [0.0] + [float(section["start"]) for section in sections[1:]]
    for point in points[1:-1]:
        if (point > boundaries[0] + .35 and point < total - .35
                and all(abs(point - other) > .20 for other in boundaries)):
            boundaries.append(point)
    boundaries.sort()
    cards = []
    for index, start in enumerate(boundaries):
        end = boundaries[index + 1] if index + 1 < len(boundaries) else total
        if end - start < .35:
            continue
        section = next((row for row in reversed(sections)
                        if float(row["start"]) <= start + .03), sections[0])
        label = re.sub(r"^\d+[.)]\s*", "", str(section.get("title", "")).strip())
        label = label or "핵심 메시지"
        source = section
        if start > float(section["start"]) + .20 and not section.get("hook"):
            next_cue = next((cue for cue in cues
                             if float(cue["end"]) > start + .05), None)
            if next_cue:
                source = {"text": next_cue["text"]}
        hook = concise_hook(source, first_limit + second_limit)
        first, second = split_hook(hook, first_limit, second_limit)
        if (cards and cards[-1]["label"] == label
                and cards[-1]["primary"] == first
                and cards[-1]["continuation"] == second):
            cards[-1]["end"] = end
        else:
            cards.append({"start": start, "end": end, "label": label,
                          "primary": first, "continuation": second})
    return cards


def retime(manifest: dict, cues: list[dict], speed: float = DEFAULT_VOICE_SPEED,
           lead: float = 0.10) -> tuple[list[dict], list[dict], float]:
    if speed <= 0:
        raise ValueError("음성 속도는 0보다 커야 합니다.")
    sections = [
        {**row, "start": lead + float(row["start"]) / speed,
         "end": lead + float(row["end"]) / speed}
        for row in manifest["sections"]
    ]
    shifted_cues = [
        {**row, "start": lead + float(row["start"]) / speed,
         "end": lead + float(row["end"]) / speed}
        for row in cues
    ]
    return sections, shifted_cues, lead + float(manifest["duration"]) / speed


def write_ass(path: Path, cues: list[dict], cards: list[dict], words: list[dict],
              style: dict, width: int, height: int,
              motion_titles: bool, total: float, outro_duration: float,
              has_outro_image: bool = False) -> None:
    size = round(width * 0.064)
    title_size = round(width * 0.073 * style["headline"]["primary_scale"])
    continuation_size = round(title_size * style["headline"]["continuation_scale"])
    label_size = round(width * .036)
    base_font = re.sub(r"-(\d+)([A-Z])", r" \1 \2",
                       style["font"]["base_file"].removesuffix(".ttf"))
    strong_font = re.sub(r"-(\d+)([A-Z])", r" \1 \2",
                         style["font"]["emphasis_file"].removesuffix(".ttf"))
    white = ass_color(style["outline"]["color"])
    primary = ass_color(style["headline"]["primary_fill"])
    dark = ass_color(style["headline"]["continuation_outline"])
    label_fill = ass_color(style["headline"]["label_fill"])
    label_bg = ass_color(style["headline"]["label_background"]).replace("&H00", "&H18", 1)
    continuation = ass_color(style["headline"]["continuation_fill"])
    lines = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {width}",
        f"PlayResY: {height}", "WrapStyle: 0", "ScaledBorderAndShadow: yes", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Caption,{base_font},{size},&H00231F1C,&H00231F1C,{white},&H70000000,-1,0,0,0,100,100,0,0,1,2,1,2,55,55,{round(height * .14)},1",
        f"Style: HeadLabel,{base_font},{label_size},{label_fill},{label_fill},{white},{label_bg},-1,0,0,0,100,100,0,0,3,5,0,8,40,40,0,1",
        f"Style: Hook,{base_font},{title_size},{primary},{primary},{white},&H70000000,-1,0,0,0,100,100,0,0,1,3,2,8,40,40,0,1",
        f"Style: HookTail,{base_font},{continuation_size},{continuation},{continuation},{dark},&H70000000,-1,0,0,0,100,100,0,0,1,3,1,8,40,40,0,1",
        f"Style: EndBrand,{strong_font},{round(width * .115)},&H00FFFFFF,&H00FFFFFF,{dark},&H70000000,-1,0,0,0,100,100,0,0,1,0,0,5,40,40,0,1",
        f"Style: EndSub,{base_font},{round(width * .044)},&H00F2F2F2,&H00F2F2F2,{dark},&H70000000,-1,0,0,0,100,100,0,0,1,0,0,5,40,40,0,1",
        "", "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    for cue in cues:
        start = max(0.0, float(cue["start"]))
        end = min(total, float(cue["end"]))
        if end <= start:
            continue
        text = str(cue["text"])
        emphasis: list[tuple[float, float, str]] = []
        if words and style["bottom_caption"]["timing_source"] == "words.json":
            candidates = []
            for word in words:
                middle = (float(word["start"]) + float(word["end"])) / 2
                token = str(word["word"])
                plain = re.sub(r"[^\w가-힣]", "", token)
                if not start <= middle < end or len(plain) < 3 or token not in text:
                    continue
                if plain in {"안녕하세요", "어떻게", "있습니다", "입니다", "합니다", "그리고"}:
                    continue
                score = len(plain) + (3 if any(char.isupper() for char in plain) else 0)
                candidates.append((score, word))
            count = style["bottom_caption"]["max_key_words_per_phrase"]
            for _, word in sorted(candidates, key=lambda entry: -entry[0])[:count]:
                word_start = max(start, float(word["start"]))
                word_end = min(end, float(word["end"]))
                if word_end - word_start < .12:
                    continue
                emphasis.append((word_start, word_end, str(word["word"])))
        segments: list[tuple[float, float, str | None]] = []
        cursor = start
        for word_start, word_end, token in sorted(emphasis):
            if word_start < cursor:
                continue
            if word_start - cursor >= .01:
                segments.append((cursor, word_start, None))
            segments.append((word_start, word_end, token))
            cursor = word_end
        if end - cursor >= .01:
            segments.append((cursor, end, None))
        for segment_start, segment_end, token in segments:
            fade_in = 80 if segment_start == start else 0
            fade_out = 80 if segment_end == end else 0
            fade = f"{{\\fad({fade_in},{fade_out})}}" if fade_in or fade_out else ""
            if token:
                position = text.find(token)
                content = (ass_escape(text[:position]) + r"{\fn" + strong_font
                           + r"\fs" + str(round(size * style["bottom_caption"]["emphasis_scale"]))
                           + "}" + ass_escape(token) + r"{\rCaption}"
                           + ass_escape(text[position + len(token):]))
            else:
                content = ass_escape(text)
            lines.append(
                f"Dialogue: 0,{ass_time(segment_start)},{ass_time(segment_end)},Caption,,0,0,0,,"
                + fade + content
            )
    if motion_titles:
        for card in cards:
            start = max(0.0, float(card["start"]))
            end = min(total, float(card["end"]))
            x = width // 2
            label_y = round(height * .107)
            primary_y = round(height * .142)
            continuation_y = round(height * .198)
            fade = min(180, round((end - start) * 1000 / 5))
            travel = round(style["motion"]["max_vertical_travel_px_at_720w"]
                           * width / 720)
            entry_ms = round(style["motion"]["entry_duration_seconds"] * 1000)
            label_effect = r"{\an8\pos(" + f"{x},{label_y})\\fad({fade},{fade})" + "}"
            primary_effect = (r"{\an8\move(" + f"{x},{primary_y + travel},{x},{primary_y},0,{entry_ms})"
                              + f"\\fad({fade},{fade})" + "}")
            lines.append(
                f"Dialogue: 2,{ass_time(start)},{ass_time(end)},HeadLabel,,0,0,0,,"
                + label_effect + ass_escape(str(card["label"]))
            )
            lines.append(
                f"Dialogue: 3,{ass_time(start)},{ass_time(end)},Hook,,0,0,0,,"
                + primary_effect + ass_escape(str(card["primary"]))
            )
            if card["continuation"]:
                tail_start = min(end - .15, start + .08)
                tail_effect = (r"{\an8\move(" + f"{x - 4},{continuation_y},{x},{continuation_y},0,{entry_ms})"
                               + f"\\fad({fade},{fade})" + "}")
                lines.append(
                    f"Dialogue: 4,{ass_time(tail_start)},{ass_time(end)},HookTail,,0,0,0,,"
                    + tail_effect + ass_escape(str(card["continuation"]))
                )
    if outro_duration > 0:
        start = total + .12
        end = total + outro_duration
        ending_text = []
        if not has_outro_image:
            ending_text.append((5, "EndBrand", round(height * .47),
                                style["outro"]["brand"]))
        ending_text.append((6, "EndSub",
                            round(height * (.59 if has_outro_image else .535)),
                            style["outro"]["subtitle"]))
        for layer, name, y, content in ending_text:
            effect = r"{\an5\pos(" + f"{width // 2},{y})\\fad(300,160)" + "}"
            lines.append(
                f"Dialogue: {layer},{ass_time(start)},{ass_time(end)},"
                f"{name},,0,0,0,," + effect + ass_escape(str(content))
            )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8-sig")


def render(root: Path, run: Path, width: int, height: int,
           motion_titles: bool, rerender: bool, speed: float | None = None,
           script_override: Path | None = None,
           background_music: Path | None = None,
           outro_image: Path | None = None,
           progress: Callable[[float, str], None] | None = None) -> Path:
    def report(percent: float, message: str) -> None:
        if progress:
            progress(max(0.0, min(100.0, percent)), message)

    report(4, "나레이션과 편집 설정 확인")
    manifest = script_metadata(read_json(run / "manifest.json"), script_override)
    cues = read_json(run / "cues.json")
    raw_words = read_json(run / "words.json") if (run / "words.json").is_file() else []
    audio = run / "narration.mp3"
    if not audio.is_file():
        raise ValueError(f"나레이션 파일이 없습니다: {audio}")
    style_file = run.parents[2] / "config" / "caption_style.json"
    if not style_file.is_file():
        raise ValueError(f"자막 스타일 설정이 없습니다: {style_file}")
    style = read_json(style_file)
    style_state = sha256(style_file)
    chosen_outro = choose_outro_image(run.parents[2], outro_image)
    if background_music is not None and not background_music.is_file():
        raise ValueError("첨부한 배경음 파일을 찾을 수 없습니다.")
    outro_duration = (float(style["outro"]["duration_seconds"])
                      if style.get("outro", {}).get("enabled", False) else 0.0)
    speed = float(style["narration"]["playback_speed"] if speed is None else speed)
    lead = float(style["narration"]["lead_seconds"])
    available_clips = source_clips(root)
    sections, cues, total = retime(manifest, cues, speed, lead)
    words = retime_words(raw_words, speed, lead)
    storyboard = storyboard_cuts(sections, available_clips, total)
    if storyboard:
        clips, points = storyboard
        mode = "대본 화면 지시 순서"
    else:
        clips = available_clips
        points, mode = cut_points(total, sections, clips, cues)
    cards = headline_cards(sections, cues, points, total, width, style)
    report(12, "컷과 자막 구간 배치")
    clip_hashes = {path.resolve(): sha256(path) for path in dict.fromkeys(clips)}
    source_state = [(str(path.resolve()), clip_hashes[path.resolve()])
                    for path in clips]
    music_state = (str(background_music.resolve()), sha256(background_music)
                   ) if background_music else None
    outro_state = (str(chosen_outro.resolve()), sha256(chosen_outro)
                   ) if chosen_outro else None
    render_key = hashlib.sha256(
        json.dumps([source_state, sha256(audio), width, height, motion_titles,
                    sections, cues, words, cards, speed, lead, style_state,
                    music_state, outro_state, "music-outro-progress-v2"],
                   ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()[:12]
    out = run / f"render-{render_key}"
    if (out / "reel.mp4").is_file() and not rerender:
        print(f"같은 영상의 기존 결과를 재사용합니다: {out / 'reel.mp4'}")
        report(100, "기존 결과 재사용 완료")
        return out / "reel.mp4"
    if out.exists():
        import datetime
        out = run / f"render-{render_key}-{datetime.datetime.now():%Y%m%d-%H%M%S}"
    out.mkdir(parents=True, exist_ok=False)
    outro_card = None
    if outro_duration and chosen_outro:
        report(17, "엔딩 이미지 준비")
        outro_card = make_outro_card(chosen_outro, out, width, height)
    plan = []
    for index, (path, start, end) in enumerate(zip(clips, points, points[1:]), 1):
        target = end - start
        available = probe_seconds(path)
        stretch = max(1.0, target / available)
        plan.append({
            "clip": str(path.resolve()), "timeline_start": round(start, 3),
            "timeline_end": round(end, 3), "source_start": 0,
            "source_used": round(min(target / stretch, available), 3),
            "playback_speed": round(1.0 / stretch, 4),
            "freeze_last_frame": 0.0,
        })
        segment = out / f"segment_{index:02d}.mp4"
        filter_string = (
            f"scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height},"
            f"setpts={stretch:.8f}*(PTS-STARTPTS),fps=30,"
            f"tpad=stop_mode=clone:stop_duration=0.15,"
            f"trim=duration={target:.3f},setpts=PTS-STARTPTS,format=yuv420p"
        )
        print(f"영상 컷 {index}/{len(clips)}: {path.name}, {target:.2f}초", flush=True)
        call([
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
            "-i", str(path), "-an", "-vf", filter_string, "-r", "30",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
            "-pix_fmt", "yuv420p", str(segment),
        ])
        report(18 + 47 * index / len(clips),
               f"영상 컷 {index}/{len(clips)} 편집 완료")
    (out / "segments.txt").write_text(
        "".join(f"file 'segment_{i:02d}.mp4'\n" for i in range(1, len(clips) + 1)),
        encoding="utf-8",
    )
    call([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
        "-f", "concat", "-safe", "0", "-i", "segments.txt",
        "-c", "copy", "video_without_audio.mp4",
    ], cwd=out)
    report(72, "컷 연결 완료")
    write_ass(out / "captions.ass", cues, cards, words, style,
              width, height, motion_titles, total, outro_duration,
              has_outro_image=outro_card is not None)
    (out / "headline_cards.json").write_text(
        json.dumps(cards, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report(78, "자막과 오디오 합성")
    print("나레이션과 자막 합성 중", flush=True)
    final_duration = total + outro_duration
    inputs = ["-i", "video_without_audio.mp4", "-i", str(audio)]
    if outro_card:
        inputs += ["-loop", "1", "-framerate", "30", "-i", str(outro_card)]
    if background_music:
        inputs += ["-stream_loop", "-1", "-i", str(background_music)]
    image_index = 2 if outro_card else None
    music_index = 3 if outro_card else 2
    video_chain = "[0:v]"
    if outro_duration:
        fade_seconds = float(style["outro"]["scene_fade_seconds"])
        video_chain += (
            f"tpad=stop_mode=clone:stop_duration={outro_duration:.3f},"
            f"fade=t=out:st={max(0, total - fade_seconds):.3f}:"
            f"d={fade_seconds + .20:.3f}"
        )
    filters = []
    if image_index is not None:
        logo_start = total + .12
        filters += [
            video_chain + "[base]",
            (f"[{image_index}:v]format=rgba,"
             "fade=t=in:st=0:d=0.32:alpha=1,"
             f"setpts=PTS-STARTPTS+{logo_start:.3f}/TB[card]"),
            (f"[base][card]overlay=x=0:y=0:shortest=0:eof_action=pass:"
             f"enable='between(t,{logo_start:.3f},{final_duration:.3f})',"
             "ass=captions.ass[v]"),
        ]
    else:
        filters.append(video_chain + "ass=captions.ass[v]" if not outro_duration
                       else video_chain + ",ass=captions.ass[v]")
    filters.append(
        f"[1:a:0]atempo={speed:.6f},adelay={round(lead * 1000)}:all=1,"
        f"apad,atrim=duration={final_duration:.3f},asetpts=N/SR/TB[voice]"
    )
    if background_music:
        filters += [
            "[voice]asplit=2[voice_main][voice_side]",
            (f"[{music_index}:a:0]atrim=duration={final_duration:.3f},"
             "asetpts=N/SR/TB,volume=0.10,"
             "afade=t=in:st=0:d=0.35,"
             f"afade=t=out:st={max(0, final_duration - .85):.3f}:d=0.85[bed]"),
            ("[bed][voice_side]sidechaincompress="
             "threshold=.035:ratio=6:attack=25:release=280[ducked]"),
            ("[voice_main][ducked]amix=inputs=2:duration=first:"
             "dropout_transition=0:normalize=0,"
             "alimiter=limit=.95:level=0[a]"),
        ]
    else:
        filters.append("[voice]anull[a]")
    final_command = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
        *(["-progress", "pipe:1", "-stats_period", "0.5"] if progress else []),
        *inputs, "-filter_complex", ";".join(filters),
        "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-c:a", "aac", "-b:a", "192k", "-t", f"{final_duration:.3f}",
        "-movflags", "+faststart", "reel.mp4",
    ]
    if progress:
        call_with_progress(
            final_command, out, final_duration,
            lambda fraction: report(78 + 18 * fraction, "영상 인코딩 중"),
        )
    else:
        call(final_command, cwd=out)
    report(96, "영상 인코딩 완료")
    (out / "edit_plan.json").write_text(json.dumps({
        "mode": mode, "narration": str(audio), "captions": str(run / "captions.srt"),
        "clips": plan, "motion_titles": motion_titles,
        "voice_speed": speed, "voice_lead_seconds": lead,
        "headline_cards": cards, "outro_duration": outro_duration,
        "background_music": str(background_music) if background_music else None,
        "outro_image": str(chosen_outro) if chosen_outro else None,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    final_video = out / "reel.mp4"
    if (not final_video.is_file() or final_video.stat().st_size == 0
            or probe_seconds(final_video) < final_duration - .12):
        raise RuntimeError("완성 영상의 길이 또는 파일 크기를 확인하지 못했습니다.")
    for temporary in [out / "video_without_audio.mp4", out / "segments.txt",
                      *(out / f"segment_{index:02d}.mp4"
                        for index in range(1, len(clips) + 1)),
                      out / "outro_svg_preview.html"]:
        temporary.unlink(missing_ok=True)
    print(f"편집 완료 ({mode}): {out / 'reel.mp4'}")
    report(100, "편집 완료")
    return out / "reel.mp4"


def main() -> int:
    parser = argparse.ArgumentParser(description="원본 컷과 시간 자막으로 세로 릴스 만들기")
    parser.add_argument("--work-root", type=Path, default=Path.cwd())
    parser.add_argument("--run", type=Path, help="나레이션 결과 폴더. 기본: 가장 최근")
    parser.add_argument("--width", type=int, default=720)
    parser.add_argument("--height", type=int, default=1280)
    parser.add_argument("--motion-titles", action="store_true", default=True,
                        help="대본 소제목과 훅을 상단 카드로 표시 (기본)")
    parser.add_argument("--no-motion-titles", action="store_false", dest="motion_titles",
                        help="상단 카드 숨기기")
    parser.add_argument("--rerender", action="store_true")
    parser.add_argument("--voice-speed", type=float,
                        help="원본 음성 기준 재생 속도. 기본: caption_style.json 값")
    parser.add_argument("--script", type=Path,
                        help="음성 내용과 같은 대본의 소제목·훅을 상단에 적용")
    parser.add_argument("--music", type=Path,
                        help="전체 영상에 낮은 볼륨으로 깔 배경음 파일")
    parser.add_argument("--outro-image", type=Path,
                        help="마지막 카드 중앙에 넣을 SVG, PNG, JPG 또는 WEBP")
    args = parser.parse_args()
    try:
        root = args.work_root.resolve()
        run = args.run.resolve() if args.run else latest_run(root)
        render(root, run, args.width, args.height, args.motion_titles, args.rerender,
               speed=args.voice_speed, script_override=args.script,
               background_music=args.music, outro_image=args.outro_image)
    except (ValueError, RuntimeError, OSError, subprocess.CalledProcessError) as exc:
        print(f"[오류] {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
