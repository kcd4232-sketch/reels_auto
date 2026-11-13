"""One command for an owner-supplied voice sample and a finished 대본.md."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

from elevenlabs_reels import clone, generate, parse_script
from render_reel import render


def main() -> int:
    parser = argparse.ArgumentParser(description="대본에서 내 목소리 릴스 자동 생성")
    parser.add_argument("--work-root", type=Path, default=Path.cwd())
    parser.add_argument("--motion-titles", action="store_true", default=True,
                        help="대본 소제목과 훅을 상단 카드로 표시 (기본)")
    parser.add_argument("--no-motion-titles", action="store_false", dest="motion_titles",
                        help="상단 카드 숨기기")
    args = parser.parse_args()
    root = args.work_root.resolve()
    script = root / "대본" / "대본.md"
    try:
        parse_script(script)
        if not (root / "elevenlabs_voice.json").is_file():
            clone(root, "Yun instar_reels", new_clone=False)
        run = generate(root, script, model="eleven_v4", regenerate=False)
        render(root, run, width=720, height=1280,
               motion_titles=args.motion_titles, rerender=False,
               script_override=script)
    except (ValueError, RuntimeError, OSError) as exc:
        print(f"[오류] {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
