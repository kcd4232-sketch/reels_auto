"""CapCut을 열지 않고 프로젝트를 미리보기 영상으로 렌더합니다(프로젝트는 읽기만 함).

클립 위치·크기·회전·투명도·키프레임, 텍스트(글꼴·흰 글씨+검은 테두리), 소리(볼륨·키프레임·페이드)를 JSON에서 읽어 그린다.
CapCut 고유 효과·필터·전환·텍스트 템플릿은 그리지 않는다(대략적인 확인용).

사용 예:
  python preview.py "초벌_v001" 편집/preview.mp4                      # CapCut 프로젝트 이름
  python preview.py 편집/02_cut/capcut_staging/초벌_v001 미리보기.mp4    # 스테이징 폴더
  python preview.py draft_content.json 미리보기.mp4 --h 540 --start 60 --end 80   # 60~80초만

알아 둘 것:
- --h 는 세로 화소(기본 540). 중간 확인은 360~540, 최종 점검은 CapCut에서 직접 내보낸 영상으로 한다.
- NVIDIA GPU가 있으면 h264_nvenc, 없으면 libx264로 인코딩한다.
- 템플릿 글꼴 파일이 이 컴퓨터에 없으면 기본 한글 글꼴(맑은 고딕/애플 SD 고딕 등)로 대신 그린다.
"""
import argparse
import functools
import json
import math
import platform
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import cv2
import numpy as np
import soundfile as sf
from PIL import Image, ImageDraw, ImageFont

sys.dont_write_bytecode = True      # 스킬 폴더에 __pycache__ 를 만들지 않는다
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as C  # noqa: E402

cv2.setNumThreads(1)
US = C.US
SR = 48000
FPS = 30


def bounds(s):
    r = s['target_timerange']
    return r['start'] / US, (r['start'] + r['duration']) / US


def key(s, prop, t, default):
    for k in s.get('common_keyframes', []):
        if k['property_type'] == prop and k.get('keyframe_list'):
            ps = k['keyframe_list']
            src = (s.get('source_timerange') or {}).get('start', 0)
            # CapCut: 영상 클립 키프레임 time_offset은 원본 시각 기준(source start 포함)
            tt = t * US + (src if s.get('source_timerange') and src > 0 else 0)
            return float(np.interp(tt, [p['time_offset'] for p in ps], [p['values'][0] for p in ps]))
    return default


# ── 글꼴 ─────────────────────────────────────────────
def fallback_fonts():
    s = platform.system()
    if s == 'Windows':
        return ['C:/Windows/Fonts/malgunbd.ttf', 'C:/Windows/Fonts/malgun.ttf', 'C:/Windows/Fonts/gulim.ttc']
    if s == 'Darwin':
        return ['/System/Library/Fonts/AppleSDGothicNeo.ttc', '/System/Library/Fonts/Supplemental/AppleGothic.ttf',
                '/Library/Fonts/NanumGothic.ttf']
    return ['/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc', '/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf']


def emoji_font():
    p = 'C:/Windows/Fonts/seguiemj.ttf'
    return p if Path(p).exists() else None


@functools.lru_cache(64)
def load_font(path, size):
    for p in [path] + fallback_fonts():
        if p and Path(p).exists():
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                continue
    return ImageFont.load_default()


def hex_rgb(c, default):
    try:
        c = c.lstrip('#')
        return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))
    except Exception:
        return default


@functools.lru_cache(512)
def text_bitmap(content, fontpath, h):
    c = json.loads(content)
    st = (c.get('styles') or [{}])[0]
    size = max(8, round(st.get('size', 8) * 7.5 * h / 1080))
    fill = tuple(int(v * 255) for v in ((st.get('fill') or {}).get('content') or {}).get('solid', {}).get('color', [1, 1, 1]))
    strokes = st.get('strokes') or []
    sw = strokes[0].get('width', 0.06) if strokes else 0
    scol = tuple(int(v * 255) for v in ((strokes[0].get('content') or {}).get('solid', {}).get('color', [0, 0, 0]))) if strokes else (0, 0, 0)
    stroke = max(1, round(size * sw)) if strokes else 0
    font = load_font((st.get('font') or {}).get('path') or fontpath, size)
    emo_path = emoji_font()
    lines = c.get('text', '').split('\n')
    rendered = []
    for line in lines:
        parts = []
        for ch in line:
            if ch in '\ufe0f\ufe0e':
                continue
            emo = emo_path and (ord(ch) > 0xffff or ch in '✅❌⚠✨')
            ft = ImageFont.truetype(emo_path, size) if emo else font
            parts.append((ch, ft, round(ft.getlength(ch)), bool(emo)))
        w = sum(x[2] for x in parts) + stroke * 6 + 2
        im = Image.new('RGBA', (max(4, w), round(size * 1.8) + stroke * 4))
        d = ImageDraw.Draw(im)
        x = stroke * 3
        for ch, ft, wd, emo in parts:
            d.text((x, size + stroke * 2), ch, font=ft, anchor='ls', fill=fill + (255,), stroke_width=stroke,
                   stroke_fill=scol + (255,), embedded_color=emo)
            x += wd
        bb = im.getbbox()
        rendered.append(im.crop(bb) if bb else im)
    if len(rendered) == 1:
        return rendered[0]
    gap = round(size * 0.25)
    W = max(r.width for r in rendered)
    H = sum(r.height for r in rendered) + gap * (len(rendered) - 1)
    out = Image.new('RGBA', (W, H))
    y = 0
    for r in rendered:
        out.paste(r, ((W - r.width) // 2, y))
        y += r.height + gap
    return out


# ── 영상 읽기 ─────────────────────────────────────────
class Reader:
    def __init__(self, path, start=0, speed=1, width=1920):
        self.path = path
        self.proc = None
        self.last = None
        if not Path(path).exists():
            self.last = np.zeros((90, 160, 4), np.uint8)
            self.last[..., 0] = 120
            self.last[..., 3] = 255         # 없는 파일은 붉은 화면
            print(f'[주의] 파일 없음: {path}', flush=True)
            return
        if Path(path).suffix.lower() in C.IMAGE_EXT:
            self.last = np.array(Image.open(path).convert('RGBA'))
            return
        info = C.media_info(path)
        sc = min(1, width / max(1, info['width']))
        self.w = max(2, round(info['width'] * sc) // 2 * 2)
        self.h = max(2, round(info['height'] * sc) // 2 * 2)
        self.proc = subprocess.Popen(['ffmpeg', '-v', 'error', '-nostdin', '-threads', '2', '-ss', f'{max(0, start):.6f}', '-i', path,
                                      '-an', '-vf', f'scale={self.w}:{self.h},setpts=(PTS-STARTPTS)/{speed},fps={FPS}',
                                      '-threads', '2', '-f', 'rawvideo', '-pix_fmt', 'rgba', 'pipe:1'],
                                     stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=8 * 1024 * 1024)

    def get(self):
        if self.proc:
            data = self.proc.stdout.read(self.w * self.h * 4)
            if len(data) == self.w * self.h * 4:
                self.last = np.frombuffer(data, np.uint8).reshape(self.h, self.w, 4)
            elif self.last is None:
                self.last = np.zeros((self.h, self.w, 4), np.uint8)
        return self.last

    def close(self):
        if self.proc:
            self.proc.stdout.close()
            if self.proc.poll() is None:
                self.proc.terminate()
            self.proc.wait(timeout=15)


@functools.lru_cache(1)
def video_encoder():
    """NVENC가 실제로 되는지 짧게 시험하고, 안 되면 libx264."""
    try:
        C.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'color=c=black:s=256x144:d=0.2', '-c:v', 'h264_nvenc', '-f', 'null', '-'])
        return ['-c:v', 'h264_nvenc', '-preset', 'p4', '-cq', '28', '-b:v', '0']
    except Exception:
        return ['-c:v', 'libx264', '-preset', 'veryfast', '-crf', '26']


def encoder(path, w, h):
    log = open(str(path) + '.encode.log', 'wb')
    p = subprocess.Popen(['ffmpeg', '-v', 'error', '-nostdin', '-y', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{w}x{h}', '-r', str(FPS),
                          '-i', 'pipe:0', '-an'] + video_encoder() + ['-pix_fmt', 'yuv420p', str(path)], stdin=subprocess.PIPE, stderr=log)
    return p, log


def animation(s, M, t):
    dur = s['target_timerange']['duration'] / US
    sc, alpha = 1.0, 1.0
    for ref in s.get('extra_material_refs', []):
        for a in M.get(ref, {}).get('animations', []) or []:
            length = a.get('duration', 0) / US
            if not length:
                continue
            if a.get('type') == 'in' and t < length:
                u = max(0, min(1, t / length))
                pop = 1 + 2.70158 * (u - 1) ** 3 + 1.70158 * (u - 1) ** 2
                sc *= .72 + .28 * pop
                alpha *= min(1, u * 3)
            if a.get('type') == 'out' and t > dur - length:
                alpha *= max(0, (dur - t) / length)
    return sc, alpha


def composite(canvas, im, s, m, t, M):
    h, w = canvas.shape[:2]
    clip = s.get('clip') or {}
    scale = clip.get('scale', {'x': 1, 'y': 1})
    pos = clip.get('transform', {'x': 0, 'y': 0})
    sx = key(s, 'KFTypeScaleX', t, scale['x'])
    sy = key(s, 'KFTypeScaleY', t, scale['y'])
    px = key(s, 'KFTypePositionX', t, pos['x'])
    py = key(s, 'KFTypePositionY', t, pos['y'])
    alpha = key(s, 'KFTypeAlpha', t, clip.get('alpha', 1))
    ani, aa = animation(s, M, t)
    alpha *= aa
    sx *= ani
    sy *= ani
    if m.get('type') in ('text', 'subtitle'):
        base = 1.0
    else:
        cr = m.get('crop') or {}
        x0, y0 = cr.get('upper_left_x', 0), cr.get('upper_left_y', 0)
        x1, y1 = cr.get('lower_right_x', 1), cr.get('lower_right_y', 1)
        ih, iw = im.shape[:2]
        im = im[round(y0 * ih):round(y1 * ih), round(x0 * iw):round(x1 * iw)]
        base = min(w / im.shape[1], h / im.shape[0])
    flip = clip.get('flip') or {}
    if flip.get('horizontal'):
        im = im[:, ::-1]
    if flip.get('vertical'):
        im = im[::-1]
    ih, iw = im.shape[:2]
    rot = math.radians(clip.get('rotation', 0))
    cx = w / 2 + px * w / 2
    cy = h / 2 - py * h / 2
    a_ = max(0, min(1, alpha))
    if abs(rot) < 1e-9:
        ww = max(1, round(iw * base * sx))
        hh = max(1, round(ih * base * sy))
        im = cv2.resize(np.ascontiguousarray(im), (ww, hh), interpolation=cv2.INTER_AREA if ww < iw else cv2.INTER_LINEAR)
        x = round(cx - ww / 2)
        y = round(cy - hh / 2)
        x0, y0, x1, y1 = max(0, x), max(0, y), min(w, x + ww), min(h, y + hh)
        if x1 <= x0 or y1 <= y0:
            return
        part = im[y0 - y:y1 - y, x0 - x:x1 - x]
        a = part[:, :, 3:4].astype(np.float32) * (a_ / 255)
        if np.all(a == 1):
            canvas[y0:y1, x0:x1] = part[:, :, :3]
        else:
            canvas[y0:y1, x0:x1] = (part[:, :, :3] * a + canvas[y0:y1, x0:x1] * (1 - a)).astype(np.uint8)
        return
    mat = np.array([[base * sx * math.cos(rot), base * sy * math.sin(rot), 0],
                    [-base * sx * math.sin(rot), base * sy * math.cos(rot), 0]], np.float32)
    mat[:, 2] = np.array([cx, cy]) - mat[:, :2] @ np.array([iw / 2, ih / 2])
    warped = cv2.warpAffine(np.ascontiguousarray(im), mat, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)
    a = warped[:, :, 3:4].astype(np.float32) * (a_ / 255)
    canvas[:] = (warped[:, :, :3] * a + canvas * (1 - a)).astype(np.uint8)


# ── 소리 ─────────────────────────────────────────────
def decode_audio(path, start, duration, speed=1):
    if Path(path).suffix.lower() == '.wav' and speed == 1:
        try:
            inf = sf.info(path)
            if inf.samplerate == SR:
                x, _ = sf.read(path, start=round(start * SR), frames=round(duration * SR), dtype='float32', always_2d=True)
                return np.repeat(x, 2, axis=1) if x.shape[1] == 1 else x[:, :2]
        except Exception:
            pass
    filters = []
    rate = speed
    while rate > 2:
        filters.append('atempo=2')
        rate /= 2
    while rate < .5:
        filters.append('atempo=.5')
        rate /= .5
    if rate != 1:
        filters.append(f'atempo={rate}')
    args = ['ffmpeg', '-v', 'error', '-ss', f'{start:.6f}', '-i', path, '-t', f'{duration:.6f}', '-vn']
    if filters:
        args += ['-af', ','.join(filters)]
    raw = C.run(args + ['-ar', str(SR), '-ac', '2', '-f', 'f32le', '-'])
    return np.frombuffer(raw, np.float32).reshape(-1, 2).copy()


def mix_audio(d, M, start, end, dest):
    mix = np.zeros((max(1, round((end - start) * SR)), 2), np.float32)
    count = 0
    for tr in d['tracks']:
        for s in tr['segments']:
            a, b = bounds(s)
            m = M.get(s['material_id'], {})
            vol = s.get('volume', 1)
            if not vol or b <= start or a >= end or not m.get('path') or not Path(m['path']).exists():
                continue
            if tr['type'] != 'audio' and not m.get('has_audio'):
                continue
            lo, hi = max(a, start), min(b, end)
            local = lo - a
            speed = s.get('speed', 1) or 1
            src = (s.get('source_timerange') or {}).get('start', 0) / US + local * speed
            try:
                x = decode_audio(m['path'], src, hi - lo, speed)
            except Exception as e:
                print('[주의] 소리 읽기 실패:', m['path'], str(e)[:100])
                continue
            n = min(len(x), round((hi - lo) * SR))
            x = x[:n]
            tt = np.arange(n) / SR + local
            env = np.full(n, vol, dtype=np.float32)
            for k in s.get('common_keyframes', []):
                if k['property_type'] == 'KFTypeVolume' and k.get('keyframe_list'):
                    ps = k['keyframe_list']
                    env *= np.interp(tt * US, [p['time_offset'] for p in ps], [p['values'][0] for p in ps]).astype(np.float32)
            for ref in s.get('extra_material_refs', []):
                f = M.get(ref, {})
                if f.get('type') == 'audio_fade':
                    fi = f.get('fade_in_duration', 0) / US
                    fo = f.get('fade_out_duration', 0) / US
                    if fi:
                        env *= np.clip(tt / fi, 0, 1)
                    if fo:
                        env *= np.clip((b - a - tt) / fo, 0, 1)
            at = round((lo - start) * SR)
            n = min(n, len(mix) - at)
            if n > 0:
                mix[at:at + n] += x[:n] * env[:n, None]
                count += 1
    raw = dest.with_suffix('.pre.wav')
    sf.write(str(raw), mix, SR, subtype='FLOAT')
    C.run(['ffmpeg', '-v', 'error', '-y', '-i', raw, '-af',
           'aresample=192000,alimiter=limit=0.794328:level=false:attack=5:release=80:latency=1,aresample=48000',
           '-c:a', 'pcm_s24le', dest])
    raw.unlink(missing_ok=True)
    print('소리 클립', count, '개 섞음', flush=True)


def render(draft_path, dest, h=540, start=0.0, end=None):
    d = C.read_draft(draft_path)
    M = C.material_index(d)
    M = {k: v[1] for k, v in M.items()}
    total = d['duration'] / US
    end = min(end if end is not None else total, total)
    if end <= start:
        C.die(f'구간이 비었습니다(프로젝트 길이 {total:.1f}초).')
    dest = Path(dest).resolve()
    dest.parent.mkdir(parents=True, exist_ok=True)
    cv = d.get('canvas_config') or {'width': 1920, 'height': 1080}
    w = round(h * cv['width'] / cv['height'] / 2) * 2
    video = dest.with_name(dest.stem + '.picture.mp4')
    audio = dest.with_name(dest.stem + '.mix.wav')
    p, log = encoder(video, w, h)
    readers = {}
    visual = []
    for ti, tr in enumerate(d['tracks']):
        if tr['type'] in ('video', 'text'):
            for s in tr['segments']:
                a, b = bounds(s)
                if b > start and a < end and s.get('visible', True):
                    visual.append((s.get('render_index', ti), ti, s))
    visual.sort(key=lambda x: (x[0], x[1]))
    pool = ThreadPoolExecutor(1)
    af = pool.submit(mix_audio, d, M, start, end, audio)
    try:
        nfr = round((end - start) * FPS)
        for f in range(nfr):
            t = start + f / FPS
            canvas = np.zeros((h, w, 3), np.uint8)
            active = set()
            for _, _, s in visual:
                a, b = bounds(s)
                if not a - 1e-7 <= t < b - 1e-7:
                    continue
                m = M.get(s['material_id'])
                if m is None:
                    continue
                local = t - a
                if m.get('type') in ('text', 'subtitle'):
                    im = np.array(text_bitmap(m['content'], m.get('font_path', ''), h))
                else:
                    active.add(s['id'])
                    if s['id'] not in readers:
                        source = (s.get('source_timerange') or {}).get('start', 0) / US + local * s.get('speed', 1)
                        readers[s['id']] = Reader(m.get('path', ''), source, s.get('speed', 1) or 1, max(w, 960))
                    im = readers[s['id']].get()
                composite(canvas, im, s, m, local, M)
            for sid in list(readers):
                if sid not in active:
                    readers.pop(sid).close()
            p.stdin.write(canvas.tobytes())
            if f % (FPS * 30) == 0:
                print(f'화면 {t:.1f}/{end:.1f}초', flush=True)
        p.stdin.close()
        if p.wait(timeout=120) != 0:
            C.die('영상 인코딩 실패: ' + str(video) + '.encode.log 를 보세요.')
        af.result()
    finally:
        for r in readers.values():
            r.close()
        if p.poll() is None:
            p.terminate()
            p.wait()
        log.close()
        pool.shutdown()
    C.run(['ffmpeg', '-v', 'error', '-y', '-i', video, '-i', audio, '-map', '0:v', '-map', '1:a', '-c:v', 'copy', '-c:a', 'aac',
           '-b:a', '192k', '-t', f'{end - start:.3f}', '-movflags', '+faststart', dest])
    for x in (video, audio, Path(str(video) + '.encode.log')):
        try:
            x.unlink()
        except OSError:
            pass
    print('저장:', dest, flush=True)


def main():
    C.setup_console()
    ap = argparse.ArgumentParser(description='CapCut 프로젝트 미리보기 렌더(CapCut 없이)')
    ap.add_argument('project', help='CapCut 프로젝트 이름, 프로젝트 폴더, 또는 draft_content.json')
    ap.add_argument('output', help='저장할 mp4')
    ap.add_argument('--h', type=int, default=540, help='세로 화소(기본 540)')
    ap.add_argument('--start', type=float, default=0.0, help='시작(초)')
    ap.add_argument('--end', type=float, default=None, help='끝(초)')
    ap.add_argument('--capcut-dir', help='CapCut 프로젝트 폴더(자동으로 못 찾을 때)')
    a = ap.parse_args()
    C.need_ffmpeg()
    folder = C.resolve_project(a.project, a.capcut_dir)
    p = Path(a.project)
    draft = p if p.is_file() else folder / 'draft_content.json'
    if a.h < 90 or a.h > 2160:
        C.die('--h 는 90~2160 사이로 주세요.')
    render(draft, a.output, a.h // 2 * 2, a.start, a.end)


if __name__ == '__main__':
    main()
