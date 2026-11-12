"""HTML 모션 카드를 영상으로 렌더한다 (1920×1080, 30fps, 마지막 0.5초 정지는 HTML이 처리).

HTML 안에 window.render(t, dur) 함수가 있어야 한다. t초 순간의 화면을 그리는 함수다(motion/cards.html 참고).

사용 예:
  python scripts/render_motion.py motion/cards.html 편집/motion/round2.mp4 --dur 3 --query "kind=title&label=ROUND 2&title=자막"
  python scripts/render_motion.py motion/cards.html 편집/motion/time.mp4 --dur 4 --query "kind=number&title=편집 시간&from=30&to=8&unit=시간"
  python scripts/render_motion.py motion/cards.html 편집/motion/check --frames 0.5,1.5,3.5 --query "kind=steps&items=녹음|맡기기|확인"   # PNG 몇 장만
  카드 종류별 예시는 motion/examples.md. 값 안에 & 가 들어가면 %26 으로 쓴다.

필요한 것: pip install playwright  →  playwright install chromium,  그리고 ffmpeg
"""
import argparse, functools, http.server, os, signal, subprocess, sys, threading, time, urllib.parse, uuid
from pathlib import Path

sys.dont_write_bytecode = True
import _common as C  # noqa: F401  # ffmpeg가 WinGet의 실제 설치 경로에 있어도 찾는다.

if os.name == 'nt' and not os.environ.get('PLAYWRIGHT_BROWSERS_PATH'):
    browser_cache = Path.home() / 'AppData' / 'Local' / 'ms-playwright'
    if browser_cache.is_dir():
        os.environ['PLAYWRIGHT_BROWSERS_PATH'] = str(browser_cache)

for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding='utf-8')
    except AttributeError:
        pass
ap = argparse.ArgumentParser(description='HTML 모션 카드 → 영상')
ap.add_argument('html', help='render(t, dur) 함수가 있는 HTML 파일')
ap.add_argument('out', help='결과 mp4 경로 (--frames면 PNG를 저장할 폴더)')
ap.add_argument('--dur', type=float, default=4.0, help='길이(초), 기본 4')
ap.add_argument('--fps', type=int, default=30)
ap.add_argument('--query', default='', help='HTML에 넘길 값, 예: "title=제목&value=10"')
ap.add_argument('--frames', default='', help='이 시각들(초, 쉼표로 구분)만 PNG로 저장')
ap.add_argument('--chromium', default='', help='크로미움 실행 파일 경로(기본: playwright가 설치한 것)')
ap.add_argument('--crf', type=int, default=18, help='화질(낮을수록 좋음), 기본 18')
ap.add_argument('--startup-timeout', type=float, default=20, help='Playwright·브라우저 시작 제한 시간(초), 기본 20')
ap.add_argument('--_worker', action='store_true', help=argparse.SUPPRESS)
ap.add_argument('--_ready-token', default='', help=argparse.SUPPRESS)
a = ap.parse_args()
if a.startup_timeout <= 0:
    ap.error('--startup-timeout은 0보다 커야 합니다.')


def stop_worker(proc):
    """시작이 멈춘 경우 이 실행이 만든 Python/Playwright 프로세스만 종료한다."""
    if proc.poll() is not None:
        return
    try:
        if os.name == 'nt':
            result = subprocess.run(['taskkill', '/PID', str(proc.pid), '/T', '/F'],
                                    capture_output=True, timeout=5)
            if result.returncode and proc.poll() is None:
                proc.kill()
        else:
            os.killpg(proc.pid, signal.SIGKILL)
    except (OSError, subprocess.TimeoutExpired):
        if proc.poll() is None:
            proc.kill()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


def supervise():
    """Playwright 시작을 별도 프로세스에서 감시해 샌드박스 대기를 제한한다."""
    token = uuid.uuid4().hex
    marker = f'__RENDER_MOTION_READY__{token}'
    args = [sys.executable, str(Path(__file__).resolve()), *sys.argv[1:],
            '--_worker', '--_ready-token', token]
    env = os.environ.copy()
    env['PYTHONUNBUFFERED'] = '1'
    proc = subprocess.Popen(args, env=env, stdout=subprocess.PIPE, text=True,
                            encoding='utf-8', errors='replace',
                            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0,
                            start_new_session=os.name != 'nt')
    ready = threading.Event()

    def forward_output():
        for line in proc.stdout:
            if line.rstrip('\r\n') == marker:
                ready.set()
            else:
                print(line, end='', flush=True)

    output_thread = threading.Thread(target=forward_output, daemon=True)
    output_thread.start()

    def finish():
        code = proc.wait()
        output_thread.join(timeout=2)
        return code

    deadline = time.monotonic() + a.startup_timeout
    try:
        while time.monotonic() < deadline:
            if ready.is_set():
                return finish()
            if proc.poll() is not None:
                return finish()
            time.sleep(0.1)
        if ready.is_set():
            return finish()
        stop_worker(proc)
        output_thread.join(timeout=2)
        print(f'[오류] Playwright/Chromium이 {a.startup_timeout:g}초 안에 시작되지 않았습니다. '
              'Windows Codex 격리 환경에서 드라이버 실행이 막힐 수 있습니다. '
              '브라우저 설치 상태를 확인하고 일반 사용자 환경에서 다시 실행하세요.', file=sys.stderr)
        return 124
    except KeyboardInterrupt:
        stop_worker(proc)
        output_thread.join(timeout=2)
        raise


if not a._worker:
    sys.exit(supervise())

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sys.exit('playwright가 없습니다. pip install playwright 한 다음 playwright install chromium 을 실행하세요.')

html = Path(a.html).resolve()
if not html.exists(): sys.exit(f'HTML 파일이 없습니다: {html}')


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args): pass


# HTML 폴더를 로컬 서버로 열어야 주소 뒤 ?값이 넘어가고 같은 폴더의 그림·글꼴을 읽을 수 있다
srv = http.server.ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(Quiet, directory=str(html.parent)))
threading.Thread(target=srv.serve_forever, daemon=True).start()
q = urllib.parse.quote(a.query, safe='=&') if a.query else ''
url = f'http://127.0.0.1:{srv.server_address[1]}/{urllib.parse.quote(html.name)}' + (f'?{q}' if q else '')

with sync_playwright() as pw:
    browser = pw.chromium.launch(executable_path=a.chromium or None)
    page = browser.new_page(viewport={'width': 1920, 'height': 1080}, device_scale_factor=1)
    errors = []
    page.on('pageerror', lambda e: errors.append(str(e)))
    page.goto(url); page.wait_for_load_state('networkidle')
    page.evaluate('document.fonts.ready')
    if not page.evaluate('typeof window.render === "function"'):
        sys.exit('HTML에 window.render(t, dur) 함수가 없습니다.')
    if a._ready_token:
        print(f'__RENDER_MOTION_READY__{a._ready_token}', flush=True)

    if a.frames:
        outdir = Path(a.out); outdir.mkdir(parents=True, exist_ok=True)
        for t in [float(x) for x in a.frames.split(',') if x.strip()]:
            page.evaluate(f'window.render({t}, {a.dur})')
            p = outdir / f'{html.stem}_{t:05.2f}.png'; page.screenshot(path=str(p)); print('저장', p)
    else:
        out = Path(a.out); out.parent.mkdir(parents=True, exist_ok=True)
        n = round(a.dur * a.fps)
        ff = subprocess.Popen(['ffmpeg', '-v', 'error', '-y', '-f', 'image2pipe', '-framerate', str(a.fps), '-i', '-',
                               '-c:v', 'libx264', '-preset', 'medium', '-crf', str(a.crf), '-pix_fmt', 'yuv420p', '-movflags', '+faststart', str(out)],
                              stdin=subprocess.PIPE)
        for i in range(n):
            page.evaluate(f'window.render({i / a.fps}, {a.dur})')
            ff.stdin.write(page.screenshot(type='png'))
            if i % (a.fps * 2) == 0: print(f'  {i / a.fps:.1f}/{a.dur:.1f}초', flush=True)
        ff.stdin.close(); ff.wait()
        if ff.returncode: sys.exit('ffmpeg 인코딩 실패')
        print('완료', out, f'({n}프레임)')
    browser.close()
    if errors: print('HTML 오류:', *errors, sep='\n  ')
srv.shutdown()
