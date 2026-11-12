"""여러 스크립트가 같이 쓰는 도구 모음입니다. 직접 실행하지 않습니다.

- 콘솔 한글 출력, ffmpeg/ffprobe 호출, 미디어 정보 읽기
- Whisper 모델 불러오기(GPU가 없으면 CPU int8로 자동 전환), 환각 문장 거르기
- CapCut 프로젝트 폴더 찾기(Windows/Mac), CapCut 실행 여부, 프로젝트 읽기
"""
import difflib
import functools
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

US = 1_000_000          # CapCut 시간 단위(마이크로초)


# ── 콘솔 ─────────────────────────────────────────────
def setup_console():
    """Windows 콘솔에서도 한글이 깨지지 않게 UTF-8로 맞춘다."""
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding='utf-8')
        except Exception:
            pass


def die(msg, code=1):
    print('[오류] ' + msg, file=sys.stderr, flush=True)
    sys.exit(code)


def mmss(t):
    """초 → 'MM:SS.ss' (한 시간이 넘으면 'H:MM:SS.ss')."""
    t = max(0.0, float(t))
    h, rest = divmod(t, 3600)
    m, s = divmod(rest, 60)
    return f'{int(h)}:{int(m):02d}:{s:05.2f}' if h >= 1 else f'{int(m):02d}:{s:05.2f}'


def us(sec):
    return int(round(sec * US))


def read_json(p):
    return json.loads(Path(p).read_text('utf-8-sig'))


def write_json(p, obj, compact=False):
    Path(p).parent.mkdir(parents=True, exist_ok=True)
    if compact:
        Path(p).write_text(json.dumps(obj, ensure_ascii=False, separators=(',', ':')), 'utf-8')
    else:
        Path(p).write_text(json.dumps(obj, ensure_ascii=False, indent=1), 'utf-8')


def sha256(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


# ── ffmpeg ───────────────────────────────────────────
def find_ffmpeg_dirs():
    """PATH에 없을 때 ffmpeg가 흔히 깔리는 곳(winget·brew 등). 방금 설치해서 PATH가 아직 안 바뀐 경우를 위해."""
    home = Path.home()
    local_roots = [Path(os.environ['LOCALAPPDATA'])] if os.environ.get('LOCALAPPDATA') else []
    if os.name == 'nt':
        # Codex의 Windows 샌드박스에서는 LOCALAPPDATA가 격리 경로일 수 있다.
        local_roots.append(home / 'AppData' / 'Local')
    cands = []
    for local_root in dict.fromkeys(local_roots):
        cands.append(local_root / 'Microsoft' / 'WinGet' / 'Links')
        pk = local_root / 'Microsoft' / 'WinGet' / 'Packages'
        if pk.exists():
            cands += sorted(pk.glob('Gyan.FFmpeg*/ffmpeg-*/bin'))
    cands += [Path('C:/ffmpeg/bin'), Path('C:/Program Files/ffmpeg/bin'),
              Path('/opt/homebrew/bin'), Path('/usr/local/bin')]
    exe = 'ffmpeg.exe' if os.name == 'nt' else 'ffmpeg'
    return [d for d in cands if (d / exe).exists()]


if not shutil.which('ffmpeg'):
    for _d in find_ffmpeg_dirs():
        os.environ['PATH'] = str(_d) + os.pathsep + os.environ.get('PATH', '')
        break


def need_ffmpeg():
    miss = [x for x in ('ffmpeg', 'ffprobe') if not shutil.which(x)]
    if miss:
        die(f'{", ".join(miss)}을(를) 찾을 수 없습니다. ffmpeg를 설치하고 PATH에 넣어 주세요. (python doctor.py 로 확인)')


def run(args, check=True):
    """명령 실행 → stdout(bytes). 실패하면 stderr 끝부분을 담아 예외."""
    p = subprocess.run([str(a) for a in args], capture_output=True)
    if check and p.returncode:
        raise RuntimeError(p.stderr.decode('utf-8', 'replace')[-3000:])
    return p.stdout


@functools.lru_cache(256)
def probe(path):
    out = run(['ffprobe', '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(path)])
    return json.loads(out)


IMAGE_EXT = ('.png', '.jpg', '.jpeg', '.webp', '.bmp')


def media_info(path):
    """영상/음성/사진 기본 정보."""
    path = str(path)
    if Path(path).suffix.lower() in IMAGE_EXT:
        from PIL import Image
        with Image.open(path) as im:
            w, h = im.size
        return dict(kind='photo', duration=0.0, width=w, height=h, has_video=True, has_audio=False, fps=0.0)
    j = probe(path)
    st = j.get('streams', [])
    v = next((s for s in st if s.get('codec_type') == 'video' and not (s.get('disposition') or {}).get('attached_pic')), None)
    a = next((s for s in st if s.get('codec_type') == 'audio'), None)
    dur = float((j.get('format') or {}).get('duration') or 0)
    fps = 0.0
    if v:
        try:
            n, d = v.get('avg_frame_rate', '0/1').split('/')
            fps = float(n) / float(d) if float(d) else 0.0
        except Exception:
            fps = 0.0
    w, h = (v or {}).get('width', 0), (v or {}).get('height', 0)
    rot = 0
    for sd in (v or {}).get('side_data_list', []) or []:
        if 'rotation' in sd:
            rot = int(sd['rotation'])
    if abs(rot) % 180 == 90:       # 세로로 찍은 휴대폰 영상
        w, h = h, w
    return dict(kind='video' if v else 'audio', duration=dur, width=w, height=h,
                has_video=bool(v), has_audio=bool(a), fps=fps)


def extract_wav16k(src, dst):
    """분석용 16kHz 모노 WAV. 이미 있고 원본보다 새것이면 그대로 쓴다."""
    src, dst = Path(src), Path(dst)
    if dst.exists() and dst.stat().st_mtime >= src.stat().st_mtime and dst.stat().st_size > 1000:
        return dst
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_suffix('.tmp.wav')
    run(['ffmpeg', '-v', 'error', '-nostdin', '-y', '-i', src, '-vn', '-ac', '1', '-ar', '16000',
         '-c:a', 'pcm_s16le', tmp])
    os.replace(tmp, dst)
    return dst


def default_workdir(media):
    """--out 을 안 주면: 원본 옆 '<원본이름>_edit' 폴더."""
    m = Path(media).resolve()
    return m.parent / f'{m.stem}_edit'


# ── Whisper ──────────────────────────────────────────
def cuda_count():
    try:
        import ctranslate2
        return ctranslate2.get_cuda_device_count()
    except Exception:
        return 0


def load_whisper(model='large-v3', device='auto', compute_type=None):
    """faster-whisper 모델. GPU(CUDA)가 없거나 실패하면 CPU int8로 자동 전환."""
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        die('faster-whisper 가 없습니다. pip install -r requirements.txt 를 먼저 실행해 주세요.')
    import numpy as np
    tries = []
    if device in ('auto', 'cuda'):
        if cuda_count() > 0:
            tries.append(('cuda', compute_type or 'float16'))
        else:
            print('[안내] CUDA GPU를 찾지 못해 CPU(int8)로 받아씁니다. 느릴 수 있습니다(긴 영상은 --model medium 권장).', flush=True)
    tries.append(('cpu', compute_type if (compute_type and device == 'cpu') else 'int8'))
    last = None
    for dev, ct in tries:
        try:
            m = WhisperModel(model, device=dev, compute_type=ct)
            # 짧은 무음으로 한 번 돌려 본다(cuDNN 등 GPU 라이브러리 문제를 여기서 잡는다)
            list(m.transcribe(np.zeros(16000, np.float32), language='ko', beam_size=1, vad_filter=False)[0])
            print(f'Whisper {model} · {dev} · {ct}', flush=True)
            return m, dev
        except Exception as e:
            last = e
            print(f'[주의] Whisper {dev}/{ct} 준비 실패: {str(e)[:200]} → 다른 방식으로 다시 시도', flush=True)
    die(f'Whisper 모델을 불러오지 못했습니다: {last}')


def norm_text(s):
    """비교용: 한글·영문·숫자만 남긴다."""
    return re.sub(r'[^0-9A-Za-z가-힣]', '', s or '')


# 무음·잡음에서 Whisper가 지어내는 문장들(유튜브 자막 학습 흔적)
HALLU_EXACT = {'감사합니다', '네감사합니다', '시청해주셔서감사합니다', '구독과좋아요부탁드립니다',
               'MBC뉴스이덕영입니다', '자막제공배달의민족', '다음영상에서만나요', '고맙습니다'}
HALLU_PART = ('시청해주셔서', '구독과좋아요', '배달의민족', '다음영상에서만나', '자막제공', 'MBC뉴스',
              '이덕영입니다', '한글자막', '자막by', '그대로적어', '반복하면반복')


def is_hallucination(text, prompt='', exact_too=True):
    n = norm_text(text)
    if not n:
        return False
    if exact_too and n in HALLU_EXACT:
        return True
    if any(h in n for h in HALLU_PART):
        return True
    p = norm_text(prompt)
    if p and len(n) >= 8:
        if n in p or difflib.SequenceMatcher(None, n, p[:len(n) + 10]).ratio() >= 0.75:
            return True       # initial_prompt를 그대로 읊은 것
    return False


# ── CapCut ───────────────────────────────────────────
def capcut_candidates():
    home = Path.home()
    c = []
    la = os.environ.get('LOCALAPPDATA')
    local_roots = [Path(la)] if la else []
    if os.name == 'nt':
        # Codex의 Windows 샌드박스는 LOCALAPPDATA를 격리 경로로 바꿀 수 있다.
        local_roots.append(home / 'AppData' / 'Local')
    for local_root in dict.fromkeys(local_roots):
        c += [local_root / 'CapCut' / 'User Data' / 'Projects' / 'com.lveditor.draft',
              local_root / 'JianyingPro' / 'User Data' / 'Projects' / 'com.lveditor.draft']
    c += [home / 'Movies' / 'CapCut' / 'User Data' / 'Projects' / 'com.lveditor.draft',
          home / 'Library' / 'Containers' / 'com.lemon.lvoverseas' / 'Data' / 'Movies' / 'CapCut' / 'User Data' / 'Projects' / 'com.lveditor.draft']
    return c


def find_capcut_dir(arg=None, required=True):
    if arg:
        p = Path(arg).expanduser()
        if p.is_dir():
            return p
        if required:
            die(f'--capcut-dir 폴더가 없습니다: {p}')
        return None
    for p in capcut_candidates():
        if p.is_dir():
            return p
    if required:
        die('CapCut 프로젝트 폴더를 찾지 못했습니다. CapCut을 한 번 실행해 프로젝트를 만든 뒤 다시 하거나 --capcut-dir 로 직접 알려 주세요.\n'
            '  Windows 기본: %LOCALAPPDATA%\\CapCut\\User Data\\Projects\\com.lveditor.draft\n'
            '  Mac 기본: ~/Movies/CapCut/User Data/Projects/com.lveditor.draft')
    return None


def capcut_running():
    """CapCut(또는 JianyingPro)이 켜져 있으면 True."""
    sysname = platform.system()
    try:
        if sysname == 'Windows':
            out = subprocess.run(['tasklist', '/NH'], capture_output=True).stdout.decode('utf-8', 'replace').lower()
            return 'capcut.exe' in out or 'jianyingpro.exe' in out
        if sysname == 'Darwin':
            r = subprocess.run(['pgrep', '-if', 'CapCut.app|VideoFusion'], capture_output=True)
            return r.returncode == 0
    except Exception as e:
        print(f'[주의] CapCut이 켜져 있는지 확인하지 못했습니다({str(e)[:80]}). CapCut을 완전히 껐는지 직접 확인해 주세요.')
        return False
    return False


def list_projects(cc):
    return sorted([p.name for p in Path(cc).iterdir() if (p / 'draft_content.json').exists()])


def resolve_project(arg, cc_arg=None):
    """프로젝트 이름, 프로젝트 폴더, 또는 draft_content.json 경로 → 프로젝트 폴더."""
    p = Path(arg).expanduser()
    if p.is_file() and p.suffix.lower() in ('.json', '.tmp'):
        return p.parent
    if p.is_dir() and (p / 'draft_content.json').exists():
        return p
    cc = find_capcut_dir(cc_arg)
    q = cc / arg
    if (q / 'draft_content.json').exists():
        return q
    names = list_projects(cc)
    near = difflib.get_close_matches(arg, names, n=5, cutoff=0.4)
    die(f'CapCut 프로젝트 "{arg}"를 찾지 못했습니다.' + (f' 비슷한 이름: {", ".join(near)}' if near else '')
        + f'\n  찾은 위치: {cc}')


def read_draft(path):
    """draft_content.json 읽기. 암호화된 버전이면 알기 쉬운 메시지로 멈춘다."""
    raw = Path(path).read_bytes()
    try:
        return json.loads(raw.decode('utf-8-sig'))
    except Exception:
        die(f'{path} 를 JSON으로 읽을 수 없습니다. 이 CapCut 버전은 프로젝트 파일을 암호화해 저장하는 것 같습니다.\n'
            '  이 경우 CapCut 조립·자막 시간 수정은 쓸 수 없고, 받아쓰기·컷 목록·SRT 자막은 쓸 수 있습니다.')


def material_index(d):
    return {m['id']: (k, m) for k, v in d.get('materials', {}).items() if isinstance(v, list)
            for m in v if isinstance(m, dict) and 'id' in m}


def now_us():
    return int(time.time() * US)
