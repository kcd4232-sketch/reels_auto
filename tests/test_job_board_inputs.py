"""Regression checks for files selected in the local editing board."""

from __future__ import annotations

import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import job_board  # noqa: E402
from render_reel import source_clips, storyboard_cuts  # noqa: E402


class BoardInputTests(unittest.TestCase):
    def test_safe_filename_keeps_extension_and_literal_percent(self) -> None:
        long_name = "가" * 180 + ".mp4"
        self.assertLessEqual(len(job_board.safe_filename(long_name)), 160)
        self.assertTrue(job_board.safe_filename(long_name).endswith(".mp4"))
        self.assertEqual(parse_qs("name=clip%252Fpart.mp4")["name"][0],
                         "clip%2Fpart.mp4")
        self.assertEqual(job_board.safe_filename("clip%2Fpart.mp4"),
                         "clip%2Fpart.mp4")

    def test_uploaded_clip_numbers_reach_storyboard(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            narration = root / "편집" / "elevenlabs" / "existing"
            narration.mkdir(parents=True)
            for name in ("manifest.json", "cues.json", "narration.mp3"):
                (narration / name).write_bytes(b"test")

            board = job_board.Board(root)
            job = board.create("장면 순서")
            board.attach(job["id"], "video", "clip (4).mp4", io.BytesIO(b"four"), 4)
            board.attach(job["id"], "video", "clip (3).mp4", io.BytesIO(b"three"), 5)
            board.jobs[job["id"]]["selected_run"] = str(narration)

            def fake_render(work: Path, narration_run: Path, **_kwargs) -> Path:
                self.assertEqual(narration_run, narration)
                clips = source_clips(work)
                self.assertEqual(["(4)" in clips[0].stem, "(3)" in clips[1].stem],
                                 [True, True])
                sections = [
                    {"start": 0.0, "visual": "클립 (3)"},
                    {"start": 2.0, "visual": "클립 (4)"},
                ]
                mapped = storyboard_cuts(sections, clips, 4.0)
                self.assertIsNotNone(mapped)
                self.assertEqual(mapped[0], [clips[1], clips[0]])
                output = narration / "render-test" / "reel.mp4"
                output.parent.mkdir()
                output.write_bytes(b"rendered")
                return output

            with patch.object(job_board, "render", side_effect=fake_render):
                board._run(job["id"])

            self.assertEqual(board.jobs[job["id"]]["status"], "done")
            self.assertTrue(board.result(job["id"]).is_file())


if __name__ == "__main__":
    unittest.main()
