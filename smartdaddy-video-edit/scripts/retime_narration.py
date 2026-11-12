"""Retiming a continuous narration track and its word timestamps together."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path


def probe_duration(path: Path) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, check=True,
    )
    return float(result.stdout.strip())


def retime_words(words: list[dict], speed: float, lead: float) -> list[dict]:
    result = []
    for item in words:
        start = float(item["start"])
        end = float(item["end"])
        if start < 0 or end <= start:
            raise ValueError(f"Invalid word interval: {item!r}")
        result.append({**item, "start": round(lead + start / speed, 3),
                       "end": round(lead + end / speed, 3)})
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Speed up uncut narration and retime words")
    parser.add_argument("--audio", type=Path, required=True)
    parser.add_argument("--words", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--speed", type=float, default=1.25)
    parser.add_argument("--lead-ms", type=int, default=100)
    args = parser.parse_args()
    if not 0.5 <= args.speed <= 2.0:
        parser.error("--speed must be between 0.5 and 2.0")
    if not 0 <= args.lead_ms <= 1000:
        parser.error("--lead-ms must be between 0 and 1000")
    audio = args.audio.resolve()
    words_path = args.words.resolve()
    if not audio.is_file() or not words_path.is_file():
        parser.error("--audio and --words must be existing files")
    words = json.loads(words_path.read_text(encoding="utf-8-sig"))
    if not isinstance(words, list):
        parser.error("--words must contain a JSON array")
    lead = args.lead_ms / 1000
    retimed = retime_words(words, args.speed, lead)
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    output_audio = out / "narration_retimed.wav"
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
         "-i", str(audio), "-vn", "-af",
         f"atempo={args.speed:.6f},adelay={args.lead_ms}:all=1",
         "-ar", "44100", "-ac", "1", "-c:a", "pcm_s16le", str(output_audio)],
        check=True,
    )
    duration = probe_duration(output_audio)
    if retimed and float(retimed[-1]["end"]) > duration + 0.08:
        raise ValueError("Last word ends after retimed audio; inspect source alignment")
    (out / "words_retimed.json").write_text(
        json.dumps(retimed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    manifest = {
        "source_audio": str(audio),
        "source_sha256": hashlib.sha256(audio.read_bytes()).hexdigest(),
        "speed": args.speed,
        "lead_seconds": lead,
        "source_duration": probe_duration(audio),
        "output_duration": duration,
        "word_count": len(retimed),
    }
    (out / "retime_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(output_audio)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"[error] {exc}", file=sys.stderr)
        raise SystemExit(1)

