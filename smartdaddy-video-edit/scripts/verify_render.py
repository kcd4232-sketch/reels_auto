"""CapCut에서 내보낸 영상을 업로드 전에 점검합니다(파일은 읽기만 함).

보는 것:
  해상도 · 프레임 수(fps) · 길이 · 소리 트랙
  검은 화면(0.5초 이상, blackdetect)
  영상 안 긴 무음(2초 넘게, silencedetect -50dB)
  통합 음량(목표 -14 LUFS ±2) · 트루 피크(-1 dBTP 이하)

사용 예:
  python verify_render.py 최종본.mp4
  python verify_render.py 최종본.mp4 --target-lufs -14 --json 점검결과.json
  python verify_render.py 최종본.mp4 --silence-db -45 --max-silence 3      # 기준 바꾸기

결과는 PASS / WARN / FAIL 표로 나온다. FAIL(소리 없음 등)이 있으면 종료 코드 1.
WARN은 '확인해 보라'는 뜻이다(예: 일부러 넣은 검은 화면 전환, 조용한 연출).
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

sys.dont_write_bytecode = True      # 스킬 폴더에 __pycache__ 를 만들지 않는다
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as C  # noqa: E402

STD_FPS = (23.976, 24, 25, 29.97, 30, 50, 59.94, 60)


def ffmpeg_log(args):
    p = subprocess.run(['ffmpeg', '-hide_banner', '-nostats'] + [str(a) for a in args], capture_output=True)
    return p.stderr.decode('utf-8', 'replace')


def main():
    C.setup_console()
    ap = argparse.ArgumentParser(description='내보낸 영상 점검')
    ap.add_argument('video')
    ap.add_argument('--target-lufs', type=float, default=-14.0)
    ap.add_argument('--lufs-tol', type=float, default=2.0)
    ap.add_argument('--max-tp', type=float, default=-1.0, help='트루 피크 상한(dBTP)')
    ap.add_argument('--silence-db', type=float, default=-50.0)
    ap.add_argument('--max-silence', type=float, default=2.0, help='이보다 긴 무음이면 WARN(초)')
    ap.add_argument('--black-min', type=float, default=0.5, help='이보다 긴 검은 화면이면 WARN(초)')
    ap.add_argument('--json', help='결과를 JSON으로도 저장')
    a = ap.parse_args()
    C.need_ffmpeg()
    v = Path(a.video).resolve()
    if not v.exists():
        C.die(f'파일이 없습니다: {v}')
    rows = []

    def row(item, status, value, note=''):
        rows.append(dict(item=item, status=status, value=value, note=note))

    j = C.probe(str(v))
    vs = next((s for s in j['streams'] if s.get('codec_type') == 'video' and not (s.get('disposition') or {}).get('attached_pic')), None)
    aus = [s for s in j['streams'] if s.get('codec_type') == 'audio']
    dur = float(j['format'].get('duration') or 0)

    # 해상도·fps
    if vs:
        w, h = vs.get('width', 0), vs.get('height', 0)
        short = min(w, h)
        row('해상도', 'PASS' if short >= 1080 else 'WARN', f'{w}x{h}', '' if short >= 1080 else '업로드용이면 1080p 이상 권장')
        try:
            n, d = vs.get('avg_frame_rate', '0/1').split('/')
            fps = float(n) / float(d)
            n2, d2 = vs.get('r_frame_rate', '0/1').split('/')
            rfps = float(n2) / float(d2)
        except Exception:
            fps = rfps = 0.0
        std = any(abs(fps - f) < 0.05 for f in STD_FPS)
        vfr = rfps and abs(rfps - fps) > 0.5
        row('프레임 수', 'PASS' if std and not vfr else 'WARN', f'{fps:.3f} fps',
            '가변 프레임(VFR)일 수 있음' if vfr else ('' if std else '흔치 않은 fps'))
        row('영상 코덱', 'PASS', f'{vs.get("codec_name")} / {vs.get("pix_fmt", "")}')
    else:
        row('영상 트랙', 'FAIL', '없음')
    row('길이', 'PASS' if dur > 0 else 'FAIL', C.mmss(dur))
    if aus:
        s0 = aus[0]
        row('소리 트랙', 'PASS', f'{len(aus)}개 · {s0.get("codec_name")} {s0.get("sample_rate")}Hz {s0.get("channels")}ch')
    else:
        row('소리 트랙', 'FAIL', '없음', '내보내기 설정에서 오디오가 꺼졌는지 확인')

    # 검은 화면
    blacks = []
    if vs:
        log = ffmpeg_log(['-i', v, '-map', '0:v:0', '-vf', f'scale=320:-2,blackdetect=d={a.black_min}:pix_th=0.10', '-an', '-f', 'null', '-'])
        for m in re.finditer(r'black_start:([\d.]+)\s+black_end:([\d.]+)\s+black_duration:([\d.]+)', log):
            blacks.append((float(m.group(1)), float(m.group(2))))
        row('검은 화면', 'PASS' if not blacks else 'WARN', f'{len(blacks)}곳',
            ', '.join(f'{C.mmss(x)}~{C.mmss(y)}' for x, y in blacks[:6]) + (' …' if len(blacks) > 6 else ''))

    # 무음 + 음량
    sils = []
    if aus:
        log = ffmpeg_log(['-i', v, '-map', '0:a:0', '-af', f'silencedetect=n={a.silence_db}dB:d={a.max_silence},ebur128=peak=true',
                          '-vn', '-f', 'null', '-'])
        starts = [float(x) for x in re.findall(r'silence_start: (-?[\d.]+)', log)]
        ends = [float(x) for x in re.findall(r'silence_end: (-?[\d.]+)', log)]
        for i, s in enumerate(starts):
            e = ends[i] if i < len(ends) else dur
            sils.append((max(0.0, s), e))
        inside = [(s, e) for s, e in sils if s > 0.5 and e < dur - 0.5]
        edge = [(s, e) for s, e in sils if (s, e) not in inside]
        note = ', '.join(f'{C.mmss(x)}~{C.mmss(y)}' for x, y in inside[:6]) + (' …' if len(inside) > 6 else '')
        if edge:
            note += (' / ' if note else '') + '처음·끝 무음 ' + ', '.join(f'{C.mmss(x)}~{C.mmss(y)}' for x, y in edge)
        row(f'긴 무음(>{a.max_silence:g}초)', 'PASS' if not inside else 'WARN', f'{len(inside)}곳', note)
        summ = log[log.rfind('Summary:'):] if 'Summary:' in log else ''
        mi = re.search(r'I:\s+(-?[\d.]+|-inf) LUFS', summ)
        mp = re.search(r'Peak:\s+(-?[\d.]+|-inf) dBFS', summ)
        ml = re.search(r'LRA:\s+([\d.]+) LU', summ)
        if mi and mi.group(1) != '-inf':
            lufs = float(mi.group(1))
            ok = abs(lufs - a.target_lufs) <= a.lufs_tol
            row('통합 음량', 'PASS' if ok else 'WARN', f'{lufs:.1f} LUFS',
                f'목표 {a.target_lufs:g}±{a.lufs_tol:g}' + ('' if ok else (' · 작음: 보이스 볼륨을 올리세요' if lufs < a.target_lufs else ' · 큼: 볼륨을 낮추세요'))
                + (f' · LRA {ml.group(1)} LU' if ml else ''))
        else:
            row('통합 음량', 'FAIL', '측정 불가', '소리가 전부 무음일 수 있음')
        if mp and mp.group(1) != '-inf':
            tp = float(mp.group(1))
            row('트루 피크', 'PASS' if tp <= a.max_tp else 'WARN', f'{tp:.1f} dBTP',
                f'{a.max_tp:g} dBTP 이하 권장' + ('' if tp <= a.max_tp else ' · 찢어지는 소리(클리핑) 위험'))
        else:
            row('트루 피크', 'WARN', '측정 불가')

    # 표 출력
    wi = max(len(r['item']) for r in rows) + 2
    print(f'점검: {v.name}')
    print('-' * 72)
    for r in rows:
        print(f'{r["status"]:<5} {r["item"]:<{wi}} {r["value"]:<22} {r["note"]}')
    print('-' * 72)
    nf = sum(r['status'] == 'FAIL' for r in rows)
    nw = sum(r['status'] == 'WARN' for r in rows)
    print(f'결과: FAIL {nf} · WARN {nw} · PASS {len(rows) - nf - nw}')
    if a.json:
        C.write_json(a.json, dict(file=v.as_posix(), rows=rows, black=blacks, silence=sils))
    sys.exit(1 if nf else 0)


if __name__ == '__main__':
    main()
