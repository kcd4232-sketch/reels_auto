"""편집 스킬을 쓰기 전에 필요한 것들이 준비됐는지 확인합니다(--fix 를 주지 않으면 아무것도 설치하거나 바꾸지 않음).

확인하는 것:
  - Python 3.10 이상
  - ffmpeg / ffprobe (영상·음성 처리)
  - Python 패키지: faster-whisper, numpy, soundfile, Pillow, opencv-python (+ 모션 카드용 playwright는 선택)
  - GPU(CUDA): 있으면 받아쓰기가 빠르고, 없으면 CPU로 느리게 동작
  - Whisper 모델 내려받기 여부(처음 한 번 약 3GB)
  - CapCut 프로젝트 폴더 위치(Windows/Mac), 읽을 수 있는 템플릿의 작업별 조건
  - 미리보기용 한글 글꼴

사용 예:
  python doctor.py
  python doctor.py --gpu-test        # 작은 모델(약 75MB)을 내려받아 GPU 받아쓰기를 실제로 한 번 돌려 본다
  python doctor.py --capcut-dir "<CapCut 프로젝트 폴더 경로>"
  python doctor.py --fix             # 사용자가 설치를 맡겼을 때: pip 패키지 · 크로미움 · (없으면) ffmpeg 설치 후 다시 확인

끝에 공통 도구와 CapCut 템플릿의 준비 상태를 따로 알려 준다.
--require-template basic/audio는 해당 프로젝트 조립 조건이 없으면 종료 코드 1.
"""
import argparse
import importlib
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

sys.dont_write_bytecode = True      # 스킬 폴더에 __pycache__ 를 만들지 않는다
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as C  # noqa: E402

HERE = Path(__file__).resolve().parent
ENCRYPTED_MSG = ('읽을 수 없는 CapCut 프로젝트가 있습니다. JSON이 아닌 프로젝트는 템플릿으로 쓸 수 없습니다. '
                 '받아쓰기·컷 목록·자막(SRT)·모션 카드는 계속 만들 수 있습니다.')


class Report:
    def __init__(self):
        self.missing = []     # 필수 항목 없음
        self.warns = []

    def ok(self, item, msg=''):
        print(f'[OK]   {item}' + (f' · {msg}' if msg else ''))

    def bad(self, item, msg, fix):
        print(f'[없음] {item} · {msg}\n       → {fix}')
        self.missing.append(item)

    def warn(self, item, msg, fix=''):
        print(f'[주의] {item} · {msg}' + (f'\n       → {fix}' if fix else ''))
        self.warns.append(item)


def ffmpeg_fix():
    s = platform.system()
    if s == 'Windows':
        return 'PowerShell에서: winget install Gyan.FFmpeg  (설치 후 터미널을 새로 열기)'
    if s == 'Darwin':
        return '터미널에서: brew install ffmpeg'
    return 'sudo apt install ffmpeg'


def template_flags(draft):
    """영상·자막 기본 초안과 로컬 오디오 포함 초안에 필요한 클립을 확인한다."""
    materials = C.material_index(draft)
    kinds = set()
    for track in draft.get('tracks', []):
        for segment in track.get('segments', []):
            material = materials.get(segment.get('material_id'), (None, {}))[1]
            kinds.add((track.get('type'), material.get('type')))
    video = ('video', 'video') in kinds
    text = any(kind == 'text' and material_type is not None for kind, material_type in kinds)
    local_audio = ('audio', 'extract_music') in kinds
    return video, text, local_audio


def fix():
    """빠진 것을 설치한다: Python 패키지, 모션 카드용 크로미움, (없으면) ffmpeg. 사용자가 설치를 맡겼을 때만 쓴다."""
    def sh(args):
        print('  $ ' + ' '.join(str(x) for x in args))
        return subprocess.run([str(x) for x in args]).returncode == 0

    print('설치를 시작합니다(사용자가 맡긴 범위: Python 패키지 · 크로미움 · ffmpeg).')
    ok = sh([sys.executable, '-m', 'pip', 'install', '-r', HERE / 'requirements.txt'])
    if ok:
        ok = sh([sys.executable, '-m', 'playwright', 'install', 'chromium']) and ok
    if not shutil.which('ffmpeg'):
        s = platform.system()
        if s == 'Windows' and shutil.which('winget'):
            sh(['winget', 'install', '--id', 'Gyan.FFmpeg', '-e', '--silent',
                '--accept-package-agreements', '--accept-source-agreements'])
        elif s == 'Darwin' and shutil.which('brew'):
            sh(['brew', 'install', 'ffmpeg'])
        else:
            print('  ffmpeg는 자동 설치 방법을 찾지 못했습니다 → ' + ffmpeg_fix())
        for d in C.find_ffmpeg_dirs():           # 방금 깔았으면 PATH가 안 바뀌었어도 이번 실행에서 찾게
            os.environ['PATH'] = str(d) + os.pathsep + os.environ.get('PATH', '')
            break
    print('설치 단계 끝. 아래에서 다시 확인합니다.')
    print('=' * 64)


def main():
    C.setup_console()
    ap = argparse.ArgumentParser(description='편집 스킬 준비물 확인')
    ap.add_argument('--capcut-dir', help='CapCut 프로젝트 폴더(자동으로 못 찾을 때)')
    ap.add_argument('--require-template', choices=('basic', 'audio'),
                    help='CapCut 템플릿 준비 상태를 종료 코드로 확인(basic=영상·자막, audio=영상·자막·로컬 오디오)')
    ap.add_argument('--gpu-test', action='store_true', help='작은 Whisper 모델로 GPU 받아쓰기를 실제로 시험')
    ap.add_argument('--fix', action='store_true', help='빠진 Python 패키지·크로미움·ffmpeg를 설치한 뒤 다시 확인')
    a = ap.parse_args()
    if a.fix:
        fix()
    r = Report()
    print(f'운영체제: {platform.system()} {platform.release()} · Python {platform.python_version()}')
    print('-' * 64)

    # 1) Python
    if sys.version_info >= (3, 10):
        r.ok('Python', platform.python_version())
    else:
        r.bad('Python', f'{platform.python_version()} (3.10 이상 필요)', 'python.org 에서 3.10 이상(3.11·3.12 권장)을 설치')

    # 2) ffmpeg
    for tool in ('ffmpeg', 'ffprobe'):
        p = shutil.which(tool)
        if p:
            try:
                ver = subprocess.run([tool, '-version'], capture_output=True).stdout.decode('utf-8', 'replace').split('\n')[0]
                r.ok(tool, ' '.join(ver.split()[:3]))
            except Exception:
                r.ok(tool, p)
        else:
            r.bad(tool, 'PATH에서 찾을 수 없음', ffmpeg_fix())
    if shutil.which('ffmpeg'):
        try:
            C.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'color=c=black:s=256x144:d=0.2', '-c:v', 'h264_nvenc', '-f', 'null', '-'])
            r.ok('GPU 영상 인코딩(NVENC)', '미리보기를 빠르게 만든다')
        except Exception:
            print('[참고] GPU 영상 인코딩(NVENC) 없음 · 미리보기는 libx264(CPU)로 만든다')

    # 3) 패키지
    req = [('faster_whisper', 'faster-whisper'), ('numpy', 'numpy'), ('soundfile', 'soundfile'), ('PIL', 'Pillow'), ('cv2', 'opencv-python')]
    for mod, pkg in req:
        try:
            m = importlib.import_module(mod)
            r.ok(pkg, getattr(m, '__version__', ''))
        except Exception as e:
            r.bad(pkg, f'불러오기 실패({str(e)[:60]})', f'pip install -r "{HERE / "requirements.txt"}"')
    try:
        importlib.import_module('playwright')
        r.ok('playwright(모션 카드용, 선택)')
    except Exception:
        print('[참고] playwright 없음(모션 카드 렌더할 때만 필요) → pip install playwright && python -m playwright install chromium')

    # 4) GPU
    n = C.cuda_count()
    if n > 0:
        vram = ''
        if shutil.which('nvidia-smi'):
            try:
                out = subprocess.run(['nvidia-smi', '--query-gpu=name,memory.total', '--format=csv,noheader'], capture_output=True).stdout.decode()
                vram = out.strip().split('\n')[0]
            except Exception:
                pass
        r.ok('GPU(CUDA)', f'{n}개 {vram}'.strip() + ' · 받아쓰기는 GPU로. 8GB 이하면 Whisper는 한 번에 하나만 돌린다')
    else:
        r.warn('GPU(CUDA)', '없음 → 받아쓰기는 CPU(int8)로 자동 전환(느림, 긴 영상은 --model medium 권장)',
               'NVIDIA 그래픽카드가 있으면 최신 드라이버를 설치. 없어도 쓸 수 있음')
    if a.gpu_test and n > 0:
        code = ('import numpy as np; from faster_whisper import WhisperModel; '
                'm = WhisperModel("tiny", device="cuda", compute_type="float16"); '
                'list(m.transcribe(np.zeros(16000, np.float32), beam_size=1)[0]); print("OK")')
        p = subprocess.run([sys.executable, '-c', code], capture_output=True, timeout=600)
        if p.returncode == 0 and b'OK' in p.stdout:
            r.ok('GPU 받아쓰기 시험', 'tiny 모델로 성공')
        else:
            r.warn('GPU 받아쓰기 시험', '실패(cuBLAS/cuDNN 라이브러리 문제일 수 있음). 스크립트는 자동으로 CPU로 전환한다',
                   (p.stderr.decode('utf-8', 'replace').strip().split('\n') or [''])[-1][:200])

    # 5) Whisper 모델 캐시
    hub = Path(os.environ.get('HF_HUB_CACHE') or (Path(os.environ.get('HF_HOME', Path.home() / '.cache' / 'huggingface')) / 'hub'))
    have = sorted(p.name.replace('models--Systran--faster-whisper-', '') for p in hub.glob('models--Systran--faster-whisper-*')) if hub.exists() else []
    if have:
        r.ok('Whisper 모델', '내려받음: ' + ', '.join(have))
    else:
        print('[참고] Whisper 모델 아직 없음 · 첫 받아쓰기 때 자동으로 내려받음(large-v3 약 3GB, 인터넷 필요)')

    # 6) CapCut
    basic_template = audio_template = None
    cc = C.find_capcut_dir(a.capcut_dir, required=False)
    if cc is None:
        r.warn('CapCut 프로젝트 폴더', '찾지 못함',
               'CapCut을 설치하고 프로젝트를 한 번 만든 뒤 다시 확인하거나 --capcut-dir 로 알려 주기. '
               '(Windows: %LOCALAPPDATA%\\CapCut\\User Data\\Projects\\com.lveditor.draft, '
               'Mac: ~/Movies/CapCut/User Data/Projects/com.lveditor.draft)')
    else:
        projs = [p for p in cc.iterdir() if (p / 'draft_content.json').exists()]
        r.ok('CapCut 프로젝트 폴더', f'{cc} · 프로젝트 {len(projs)}개')
        if not (cc / 'root_meta_info.json').exists():
            r.warn('CapCut 프로젝트 목록', 'root_meta_info.json 없음 → --install(자동 등록)은 못 씀')
        if C.capcut_running():
            print('[참고] CapCut이 지금 켜져 있음 · 프로젝트 등록(--install)과 자막 시간 수정 전에는 꺼야 함')
        if projs:
            readable = []
            unreadable = []
            for project in sorted(projs, key=lambda p: (p / 'draft_content.json').stat().st_mtime, reverse=True):
                try:
                    draft = C.read_json(project / 'draft_content.json')
                    readable.append((project, draft, template_flags(draft)))
                except (OSError, ValueError, KeyError, TypeError, AttributeError):
                    unreadable.append(project.name)
            if readable:
                latest, d, _ = readable[0]
                platform_info = d.get('last_modified_platform') or d.get('platform') or {}
                ver = platform_info.get('app_version', '?') if isinstance(platform_info, dict) else '?'
                r.ok('최근 읽을 수 있는 프로젝트', f'"{latest.name}" JSON 읽힘 · CapCut {ver}')
                basic_template = next((p for p, _, (v, t, _) in readable if v and t), None)
                audio_template = next((p for p, _, (v, t, a_local) in readable if v and t and a_local), None)
            if unreadable:
                r.warn('프로젝트 JSON', f'{len(unreadable)}개를 읽을 수 없음: {", ".join(unreadable[:3])}', ENCRYPTED_MSG)
        if basic_template:
            r.ok('CapCut 기본 템플릿(영상·자막)', basic_template.name)
        else:
            r.warn('CapCut 기본 템플릿(영상·자막)', '읽을 수 있는 영상 클립과 텍스트 클립이 한 프로젝트에 없음',
                   'CapCut에서 영상·자막이 든 프로젝트를 저장해 템플릿으로 사용')
        if audio_template:
            r.ok('CapCut 음향 템플릿(로컬 오디오)', audio_template.name)
        else:
            r.warn('CapCut 음향 템플릿(로컬 오디오)', '별도 음성·효과음·BGM이 필요한 초안은 아직 조립 준비가 안 됨',
                   '영상·자막·로컬 파일 오디오 클립이 함께 든 프로젝트를 저장')

    # 7) 한글 글꼴(미리보기)
    fonts = {'Windows': ['C:/Windows/Fonts/malgun.ttf', 'C:/Windows/Fonts/malgunbd.ttf'],
             'Darwin': ['/System/Library/Fonts/AppleSDGothicNeo.ttc', '/System/Library/Fonts/Supplemental/AppleGothic.ttf']}.get(platform.system(), [])
    f = next((x for x in fonts if Path(x).exists()), None)
    if f:
        r.ok('한글 글꼴(미리보기)', Path(f).name)
    elif fonts:
        r.warn('한글 글꼴(미리보기)', '기본 한글 글꼴을 못 찾음 · 미리보기 자막이 깨질 수 있음(CapCut 프로젝트에는 영향 없음)')

    print('-' * 64)
    if r.missing:
        print(f'필수 항목 {len(r.missing)}개가 없습니다: {", ".join(r.missing)}. 위 → 안내대로 설치한 뒤 다시 실행해 주세요.'
              + ('' if a.fix else ' (설치를 맡기려면: python doctor.py --fix)'))
        sys.exit(1)
    if a.require_template and not (audio_template if a.require_template == 'audio' else basic_template):
        print(f'공통 도구는 준비됐지만 요청한 CapCut 템플릿({a.require_template})은 준비되지 않았습니다.')
        sys.exit(1)
    state = ('기본·음향 초안 준비됨' if audio_template else
             '기본 초안 준비됨 · 음향 포함 초안은 템플릿 미준비' if basic_template else
             'CapCut 초안은 템플릿 미준비')
    print(f'공통 도구 준비됨 · {state}' + (f' (주의 {len(r.warns)}개)' if r.warns else ''))


if __name__ == '__main__':
    main()
