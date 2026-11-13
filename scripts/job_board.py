"""Local job board for the existing ElevenLabs and render_reel pipeline."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import mimetypes
import os
import queue
import shutil
import subprocess
import threading
import uuid
import webbrowser
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from elevenlabs_reels import generate, parse_script
from render_reel import render


VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi"}
FILE_EXTENSIONS = {
    "video": VIDEO_EXTENSIONS,
    "script": {".md"},
    "music": {".mp3", ".wav", ".m4a", ".aac", ".ogg"},
    "outro": {".svg", ".png", ".jpg", ".jpeg", ".webp"},
}
MAX_UPLOAD = 2 * 1024 * 1024 * 1024
MAX_SCRIPT_CHARS = 12_000
MAX_ASSET_SIZE = {
    "video": MAX_UPLOAD,
    "script": 2 * 1024 * 1024,
    "music": 250 * 1024 * 1024,
    "outro": 25 * 1024 * 1024,
}


class BoardError(Exception):
    pass


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def safe_filename(value: str) -> str:
    name = Path(value.replace("\\", "/")).name.strip()
    name = "".join(c for c in name if c not in '<>:"/\\|?*' and ord(c) >= 32)
    suffix = Path(name).suffix
    if suffix and len(suffix) < 16:
        stem = name[:-len(suffix)][:160 - len(suffix)].rstrip(" .") or "file"
        return stem + suffix
    return name[:160].rstrip(" .") or "file"


class Board:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.output = self.root / "편집" / "elevenlabs"
        self.data = self.root / "편집" / "job_board"
        self.data.mkdir(parents=True, exist_ok=True)
        self.state_file = self.data / "jobs.json"
        self.lock = threading.RLock()
        self.jobs: dict[str, dict] = {}
        self.uploading: dict[str, int] = {}
        self.pending: queue.Queue[str] = queue.Queue()
        self._load()
        threading.Thread(target=self._worker, daemon=True, name="reel-job-worker").start()

    def _load(self) -> None:
        if not self.state_file.is_file():
            return
        data = json.loads(self.state_file.read_text(encoding="utf-8"))
        for job in data.get("jobs", []):
            job.setdefault("script_text", "")
            job.setdefault("progress", 100 if job["status"] == "done" else 0)
            job.setdefault("progress_message", "")
            job.setdefault("started_at", None)
            job.setdefault("completed_at", job.get("updated_at") if job["status"] == "done" else None)
            if job["status"] in {"queued", "editing"}:
                job["status"] = "failed"
                job["error"] = "프로그램이 작업 중 종료됐습니다. 이 작업만 다시 실행하세요."
                job["progress_message"] = "중단됨"
            self.jobs[job["id"]] = job

    def _save(self) -> None:
        temporary = self.state_file.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps({"jobs": list(self.jobs.values())}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, self.state_file)

    def _job(self, job_id: str) -> dict:
        try:
            return self.jobs[job_id]
        except KeyError as exc:
            raise BoardError("작업을 찾을 수 없습니다.") from exc

    def _editable(self, job: dict) -> None:
        if job["status"] in {"queued", "editing"}:
            raise BoardError("대기·편집 중인 작업의 파일은 변경할 수 없습니다.")
        if self.uploading.get(job["id"], 0):
            raise BoardError("파일 업로드가 끝난 뒤 다시 시도하세요.")

    @staticmethod
    def _invalidate_result(job: dict) -> None:
        if job["status"] == "done":
            job["status"] = "waiting"
            job["result"] = None
            job["narration_run"] = None
            job["input_mapping"] = []
        elif job["status"] == "failed":
            job["error"] = None
            job["status"] = "waiting"
        job["progress"] = 0
        job["progress_message"] = ""
        job["completed_at"] = None
        job["started_at"] = None

    def _latest(self) -> Path | None:
        if not self.output.is_dir():
            return None
        required = ("manifest.json", "cues.json", "narration.mp3")
        choices = [path for path in self.output.iterdir()
                   if path.is_dir() and all((path / name).is_file() for name in required)]
        return max(choices, key=lambda path: (path / "manifest.json").stat().st_mtime_ns,
                   default=None)

    def missing(self, job: dict) -> list[str]:
        missing = []
        if not any(file["kind"] == "video"
                   and (self.data / job["id"] / file["stored"]).is_file()
                   for file in job["files"]):
            missing.append("원본 영상 1개 이상")
        if job["mode"] == "recent":
            if not self._latest():
                missing.append("최근 나레이션 결과 또는 대본")
        else:
            has_script = any(file["kind"] == "script"
                             and (self.data / job["id"] / file["stored"]).is_file()
                             for file in job["files"])
            if not job.get("script_text", "").strip() and not has_script and not (self.root / "대본" / "대본.md").is_file():
                missing.append("대본 입력 또는 대본.md")
            if not (self.root / "elevenlabs_voice.json").is_file():
                missing.append("등록된 복제 목소리")
        return missing

    def snapshot(self) -> dict:
        with self.lock:
            jobs = [
                {**job, "missing": self.missing(job)}
                for job in sorted(self.jobs.values(), key=lambda item: item["created_at"])
            ]
            latest = self._latest()
            style_path = self.root / "config" / "caption_style.json"
            style = json.loads(style_path.read_text(encoding="utf-8")) if style_path.is_file() else {}
            return {
                "jobs": jobs,
                "output_folder": str(self.output),
                "recent_narration": str(latest) if latest else None,
                "voice_speed": style.get("narration", {}).get("playback_speed"),
                "default_script": str(self.root / "대본" / "대본.md")
                if (self.root / "대본" / "대본.md").is_file() else None,
            }

    def create(self, name: str = "") -> dict:
        with self.lock:
            job_id = uuid.uuid4().hex[:12]
            job = {
                "id": job_id,
                "name": name.strip()[:120] or "새 작업",
                "mode": "recent" if self._latest() else "script",
                "motion_titles": True,
                "files": [],
                "script_text": "",
                "status": "waiting",
                "progress": 0,
                "progress_message": "",
                "error": None,
                "result": None,
                "selected_run": None,
                "input_mapping": [],
                "created_at": now(),
                "updated_at": now(),
                "started_at": None,
                "completed_at": None,
            }
            self.jobs[job_id] = job
            (self.data / job_id / "uploads").mkdir(parents=True, exist_ok=False)
            self._save()
            return job

    def update(self, job_id: str, values: dict) -> dict:
        with self.lock:
            job = self._job(job_id)
            self._editable(job)
            if "mode" in values and values["mode"] not in {"recent", "script"}:
                raise BoardError("음성 방식을 선택하세요.")
            if "script_text" in values and (
                    not isinstance(values["script_text"], str)
                    or len(values["script_text"]) > MAX_SCRIPT_CHARS):
                raise BoardError(f"직접 입력 대본은 {MAX_SCRIPT_CHARS:,}자 이하여야 합니다.")
            before = copy.deepcopy(job)
            if "name" in values:
                job["name"] = str(values["name"]).strip()[:120] or job["name"]
            if "mode" in values:
                if job["mode"] != values["mode"]:
                    self._invalidate_result(job)
                job["mode"] = values["mode"]
            if "motion_titles" in values:
                if job["motion_titles"] != bool(values["motion_titles"]):
                    self._invalidate_result(job)
                job["motion_titles"] = bool(values["motion_titles"])
            if "script_text" in values:
                text_value = values["script_text"]
                if job.get("script_text", "") != text_value:
                    self._invalidate_result(job)
                    job["script_text"] = text_value
                    if text_value.strip():
                        job["mode"] = "script"
            job["updated_at"] = now()
            try:
                self._save()
            except Exception:
                self.jobs[job_id] = before
                raise
            return job

    def attach(self, job_id: str, kind: str, name: str, stream,
               length: int, replace_id: str | None = None) -> dict:
        if kind not in FILE_EXTENSIONS:
            raise BoardError("지원하지 않는 파일 항목입니다.")
        name = safe_filename(name)
        if Path(name).suffix.lower() not in FILE_EXTENSIONS[kind]:
            raise BoardError("영상·대본·배경음·엔딩 이미지 형식을 확인하세요.")
        is_svg = kind == "outro" and Path(name).suffix.lower() == ".svg"
        limit = 2 * 1024 * 1024 if is_svg else MAX_ASSET_SIZE[kind]
        if length <= 0 or length > limit:
            raise BoardError("SVG는 2MB 이하여야 합니다." if is_svg
                             else "파일이 비었거나 해당 항목의 크기 제한을 초과합니다.")
        with self.lock:
            job = self._job(job_id)
            self._editable(job)
            old = next((f for f in job["files"] if f["id"] == replace_id), None)
            if replace_id and (not old or old["kind"] != kind):
                raise BoardError("교체할 파일을 찾을 수 없습니다.")
            file_id = uuid.uuid4().hex[:12]
            destination = self.data / job_id / "uploads" / f"{file_id}_{name}"
            self.uploading[job_id] = self.uploading.get(job_id, 0) + 1
        digest = hashlib.sha256()
        try:
            with destination.open("xb") as output:
                remaining = length
                while remaining:
                    chunk = stream.read(min(1024 * 1024, remaining))
                    if not chunk:
                        raise BoardError("업로드가 완료되기 전에 연결이 끊겼습니다.")
                    output.write(chunk)
                    digest.update(chunk)
                    remaining -= len(chunk)
            with self.lock:
                job = self._job(job_id)
                before = copy.deepcopy(job)
                if kind in {"script", "music", "outro"} and not old:
                    old = next((f for f in job["files"] if f["kind"] == kind), None)
                if old:
                    job["files"].remove(old)
                self._invalidate_result(job)
                entry = {"id": file_id, "kind": kind, "name": name,
                         "size": length, "sha256": digest.hexdigest(),
                         "stored": f"uploads/{destination.name}"}
                job["files"].append(entry)
                if kind == "script":
                    job["mode"] = "script"
                if kind == "video" and job["name"] == "새 작업":
                    job["name"] = Path(name).stem[:120]
                job["updated_at"] = now()
                try:
                    self._save()
                except Exception:
                    self.jobs[job_id] = before
                    raise
                if old:
                    try:
                        (self.data / job_id / old["stored"]).unlink(missing_ok=True)
                    except OSError as cleanup_error:
                        print(f"[작업 보드] 이전 첨부 정리 오류: {cleanup_error}", flush=True)
                return entry
        except Exception:
            destination.unlink(missing_ok=True)
            raise
        finally:
            with self.lock:
                self.uploading[job_id] -= 1
                if not self.uploading[job_id]:
                    del self.uploading[job_id]

    def remove(self, job_id: str, file_id: str) -> None:
        with self.lock:
            job = self._job(job_id)
            self._editable(job)
            entry = next((f for f in job["files"] if f["id"] == file_id), None)
            if not entry:
                raise BoardError("첨부 파일을 찾을 수 없습니다.")
            job["files"].remove(entry)
            (self.data / job_id / entry["stored"]).unlink(missing_ok=True)
            self._invalidate_result(job)
            job["updated_at"] = now()
            self._save()

    def enqueue(self, job_ids: list[str]) -> list[str]:
        with self.lock:
            if not job_ids:
                raise BoardError("편집할 작업을 선택하세요.")
            jobs = [self._job(job_id) for job_id in dict.fromkeys(job_ids)]
            for job in jobs:
                if self.uploading.get(job["id"], 0):
                    raise BoardError(f"{job['name']}: 파일 업로드 중입니다.")
                if job["status"] in {"queued", "editing"}:
                    raise BoardError(f"이미 실행 중인 작업입니다: {job['name']}")
                missing = self.missing(job)
                if missing:
                    raise BoardError(f"{job['name']}: 필요한 파일 — {', '.join(missing)}")
            for job in jobs:
                job["selected_run"] = str(self._latest()) if job["mode"] == "recent" else None
                job["status"] = "queued"
                job["progress"] = 0
                job["progress_message"] = "실행 순서 대기"
                job["error"] = None
                job["result"] = None
                job["started_at"] = None
                job["completed_at"] = None
                job["updated_at"] = now()
            self._save()
            for job in jobs:
                self.pending.put(job["id"])
            return [job["id"] for job in jobs]

    def _set_progress(self, job_id: str, value: float, message: str) -> None:
        with self.lock:
            job = self._job(job_id)
            if job["status"] != "editing":
                return
            job["progress"] = max(int(job.get("progress", 0)), min(99, round(value)))
            job["progress_message"] = message
            job["updated_at"] = now()
            self._save()

    def _worker(self) -> None:
        while True:
            job_id = self.pending.get()
            try:
                self._run(job_id)
            except Exception as exc:
                try:
                    with self.lock:
                        job = self.jobs.get(job_id)
                        if job:
                            job["status"] = "failed"
                            job["error"] = f"{type(exc).__name__}: {exc}"
                            job["progress_message"] = "편집 실패"
                            job["updated_at"] = now()
                            self._save()
                except Exception as record_error:
                    print(f"[작업 보드] 작업 실패 기록 오류: {record_error}", flush=True)
            finally:
                self.pending.task_done()

    def _run(self, job_id: str) -> None:
        with self.lock:
            job = self._job(job_id)
            job["status"] = "editing"
            job["progress"] = 4
            job["progress_message"] = "입력 파일 준비"
            job["started_at"] = now()
            job["completed_at"] = None
            job["updated_at"] = now()
            self._save()
            files = [dict(item) for item in job["files"]]
            mode = job["mode"]
            selected_run = job["selected_run"]
            motion_titles = job["motion_titles"]
            script_text = job.get("script_text", "")
        try:
            work = self.data / job_id / f"run-{uuid.uuid4().hex[:8]}"
            source = work / "원본"
            source.mkdir(parents=True, exist_ok=False)
            mapping = []
            videos = [item for item in files if item["kind"] == "video"]
            for index, item in enumerate(videos, 1):
                upload = self.data / job_id / item["stored"]
                staged = source / f"{index:03d}_{item['id']}_{safe_filename(item['name'])}"
                shutil.copy2(upload, staged)
                mapping.append({"file_id": item["id"], "kind": "video",
                                "name": item["name"],
                                "sha256": item["sha256"], "staged": str(staged)})
                self._set_progress(job_id, 5 + 12 * index / len(videos),
                                   f"원본 영상 준비 {index}/{len(videos)}")
            assets = {}
            for kind in ("music", "outro"):
                item = next((entry for entry in files if entry["kind"] == kind), None)
                if item:
                    asset = self.data / job_id / item["stored"]
                    if not asset.is_file():
                        raise BoardError(f"{item['name']}: 첨부 파일을 찾을 수 없습니다.")
                    assets[kind] = asset
                    mapping.append({"file_id": item["id"], "kind": kind,
                                    "name": item["name"],
                                    "sha256": item["sha256"], "staged": str(asset)})
            script_path = None
            if mode == "script":
                if script_text.strip():
                    script = work / "대본_직접입력.md"
                    script.write_text(script_text, encoding="utf-8")
                else:
                    script = next((self.data / job_id / item["stored"]
                                   for item in files if item["kind"] == "script"),
                                  self.root / "대본" / "대본.md")
                script_path = script
                self._set_progress(job_id, 20, "나레이션 준비")
                narration_run = generate(self.root, script, model="eleven_v4", regenerate=False)
            else:
                narration_run = Path(selected_run)
                default_script = self.root / "대본" / "대본.md"
                if default_script.is_file():
                    spoken, _ = parse_script(default_script)
                    stored = json.loads(
                        (narration_run / "manifest.json").read_text(encoding="utf-8-sig")
                    )
                    if spoken == stored.get("text"):
                        script_path = default_script
            if script_path and script_path.is_file():
                mapping.append({
                    "kind": "script",
                    "name": "직접 입력 대본" if script_text.strip() and mode == "script"
                            else script_path.name,
                    "sha256": hashlib.sha256(script_path.read_bytes()).hexdigest(),
                    "staged": str(script_path),
                })
            self._set_progress(job_id, 32, "영상 편집 시작")
            result = render(work, narration_run, width=720, height=1280,
                            motion_titles=motion_titles, rerender=False,
                            script_override=script_path,
                            background_music=assets.get("music"),
                            outro_image=assets.get("outro"),
                            progress=lambda value, message: self._set_progress(
                                job_id, 32 + .64 * value, message))
            self._set_progress(job_id, 97, "완성 영상 확인")
            result = result.resolve()
            if not result.is_relative_to(self.output.resolve()) or not result.is_file():
                raise RuntimeError("완성 영상이 기존 출력 폴더에 생성되지 않았습니다.")
            with self.lock:
                job = self._job(job_id)
                job["status"] = "done"
                job["progress"] = 100
                job["progress_message"] = "편집 완료"
                job["result"] = str(result)
                job["narration_run"] = str(narration_run)
                job["input_mapping"] = mapping
                job["updated_at"] = now()
                job["completed_at"] = now()
                self._save()
        except Exception as exc:
            with self.lock:
                job = self._job(job_id)
                job["status"] = "failed"
                job["error"] = f"{type(exc).__name__}: {exc}"
                job["progress_message"] = "편집 실패"
                job["updated_at"] = now()
                self._save()

    def result(self, job_id: str) -> Path:
        with self.lock:
            job = self._job(job_id)
            if job["status"] != "done" or not job["result"]:
                raise BoardError("아직 완성 영상이 없습니다.")
            path = Path(job["result"]).resolve()
            if not path.is_relative_to(self.output.resolve()) or not path.is_file():
                raise BoardError("완성 영상 파일을 찾을 수 없습니다.")
            return path

    def poster(self, job_id: str) -> Path:
        video = self.result(job_id)
        poster = video.with_name("poster.jpg")
        if poster.is_file():
            return poster
        with self.lock:
            if not poster.is_file():
                temporary = video.with_name("poster.pending.jpg")
                try:
                    subprocess.run(
                        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin",
                         "-y", "-ss", "1.0", "-i", str(video), "-frames:v", "1",
                         "-vf", "scale=360:-2", "-q:v", "3", str(temporary)],
                        check=True, capture_output=True, text=True,
                    )
                    os.replace(temporary, poster)
                except (OSError, subprocess.CalledProcessError) as exc:
                    raise BoardError(f"영상 미리보기를 만들 수 없습니다: {exc}") from exc
                finally:
                    temporary.unlink(missing_ok=True)
        return poster


def open_local(path: Path) -> None:
    try:
        if os.name == "nt":
            if path.is_dir():
                subprocess.Popen(["explorer.exe", str(path)])
            else:
                os.startfile(path)  # type: ignore[attr-defined]
        else:
            subprocess.Popen(["xdg-open", str(path)])
    except OSError as exc:
        raise BoardError(f"폴더나 영상을 열 수 없습니다: {exc}") from exc


def handler_factory(board: Board, ui: Path):
    class Handler(BaseHTTPRequestHandler):
        def _json(self, status: int, value: dict | list) -> None:
            body = json.dumps(value, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _body(self) -> dict:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 0 or length > 65536:
                raise BoardError("요청 내용이 너무 큽니다.")
            value = json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(value, dict):
                raise BoardError("잘못된 요청 형식입니다.")
            return value

        def _parts(self):
            parsed = urlsplit(self.path)
            return parsed.path.strip("/").split("/"), parse_qs(parsed.query)

        def _serve_file(self, path: Path, content_type: str) -> None:
            size = path.stat().st_size
            start, end = 0, size - 1
            range_header = self.headers.get("Range", "")
            if range_header.startswith("bytes="):
                bounds = range_header[6:].split("-", 1)
                start = int(bounds[0] or 0)
                end = min(size - 1, int(bounds[1])) if bounds[1] else size - 1
                if start >= size or end < start:
                    self.send_error(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                    return
            self.send_response(HTTPStatus.PARTIAL_CONTENT if range_header else HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(end - start + 1))
            self.send_header("Accept-Ranges", "bytes")
            if range_header:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.end_headers()
            with path.open("rb") as source:
                source.seek(start)
                remaining = end - start + 1
                while remaining:
                    chunk = source.read(min(1024 * 1024, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)

        def do_GET(self):
            try:
                parts, _ = self._parts()
                if parts == ["api", "state"]:
                    self._json(200, board.snapshot())
                elif len(parts) == 4 and parts[:2] == ["api", "jobs"] and parts[3] == "video":
                    self._serve_file(board.result(parts[2]), "video/mp4")
                elif len(parts) == 4 and parts[:2] == ["api", "jobs"] and parts[3] == "poster":
                    self._serve_file(board.poster(parts[2]), "image/jpeg")
                else:
                    files = {"": "job_board.html", "app.css": "app.css", "app.js": "app.js"}
                    name = files.get("/".join(parts))
                    if name is None:
                        self.send_error(HTTPStatus.NOT_FOUND)
                        return
                    file = ui / name
                    self._serve_file(file, mimetypes.guess_type(file)[0] or "text/html")
            except (BoardError, ValueError) as exc:
                self._json(400, {"error": str(exc)})
            except (BrokenPipeError, ConnectionResetError):
                pass

        def do_POST(self):
            try:
                parts, params = self._parts()
                if parts == ["api", "jobs"]:
                    job = board.create(str(self._body().get("name", "")))
                    self._json(201, {"job": job})
                elif parts == ["api", "jobs", "queue"]:
                    self._json(200, {"queued": board.enqueue(self._body().get("ids", []))})
                elif parts == ["api", "open-folder"]:
                    try:
                        board.output.mkdir(parents=True, exist_ok=True)
                    except OSError as exc:
                        raise BoardError(f"결과 폴더를 만들 수 없습니다: {exc}") from exc
                    open_local(board.output)
                    self._json(200, {"ok": True})
                elif len(parts) == 4 and parts[:2] == ["api", "jobs"] and parts[3] == "files":
                    kind = params.get("kind", [""])[0]
                    name = params.get("name", [""])[0]
                    length = int(self.headers.get("Content-Length", "0"))
                    entry = board.attach(parts[2], kind, name, self.rfile, length,
                                         params.get("replace", [None])[0])
                    self._json(201, {"file": entry})
                elif len(parts) == 4 and parts[:2] == ["api", "jobs"] and parts[3] == "queue":
                    self._json(200, {"queued": board.enqueue([parts[2]])})
                elif len(parts) == 4 and parts[:2] == ["api", "jobs"] and parts[3] == "open":
                    open_local(board.result(parts[2]))
                    self._json(200, {"ok": True})
                else:
                    self.send_error(HTTPStatus.NOT_FOUND)
            except (BoardError, ValueError, json.JSONDecodeError) as exc:
                self._json(400, {"error": str(exc)})

        def do_PATCH(self):
            try:
                parts, _ = self._parts()
                if len(parts) == 3 and parts[:2] == ["api", "jobs"]:
                    self._json(200, {"job": board.update(parts[2], self._body())})
                else:
                    self.send_error(HTTPStatus.NOT_FOUND)
            except (BoardError, ValueError, json.JSONDecodeError) as exc:
                self._json(400, {"error": str(exc)})

        def do_DELETE(self):
            try:
                parts, _ = self._parts()
                if len(parts) == 5 and parts[:2] == ["api", "jobs"] and parts[3] == "files":
                    board.remove(parts[2], parts[4])
                    self._json(200, {"ok": True})
                else:
                    self.send_error(HTTPStatus.NOT_FOUND)
            except BoardError as exc:
                self._json(400, {"error": str(exc)})

        def log_message(self, format, *args):
            print("[작업 보드] " + format % args, flush=True)

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(description="릴스 영상 편집 작업 보드")
    parser.add_argument("--work-root", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    board = Board(args.work_root)
    ui = Path(__file__).resolve().parent.parent / "ui"
    server = ThreadingHTTPServer(("127.0.0.1", args.port), handler_factory(board, ui))
    url = f"http://127.0.0.1:{server.server_port}/"
    print(f"영상 편집 작업 보드: {url}", flush=True)
    print(f"결과 폴더: {board.output}", flush=True)
    if not args.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
