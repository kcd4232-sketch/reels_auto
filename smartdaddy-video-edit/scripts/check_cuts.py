"""남긴 문장 클립을 하나씩 다시 받아써서 컷이 제대로 됐는지 검사합니다(파일은 읽기만 함).

컷 계획(plan.json)의 구간마다 그 소리만 잘라 따로 받아쓴다. 한 번에 받아쓰면 Whisper가 반복을 지워 버려서
남은 반복이 안 보이기 때문이다. 이런 것을 찾아 표시한다.
  - 반복: 같은 낱말·구절이 바로 이어서 두 번 ("AI는 AI는", "제가 요청한, 제가 요청한")
  - "다시": 녹음 중 다시 하겠다고 한 말이 남음
  - 끝 잘림 의심: 클립 끝 0.1초가 아직 소리가 큼(말 끝이 약한 "~볼게요"가 잘렸을 수 있음)
  - 앞뒤 딸림 의심: 다시 받아쓴 글이 컷 계획의 글보다 많이 길거나 짧음

결과: <plan 폴더>/check_cuts.md (사람이 읽는 표) — 표시된 클립만 들어 보면 된다.

사용 예:
  python check_cuts.py 편집/02_cut/plan.json 녹화.mp4
  python check_cuts.py 편집/02_cut/plan.json 마이크.wav --model medium
"""
import argparse
import difflib
import re
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as C  # noqa: E402

SR = 16000
RETAKE = ('다시', '다시할게요', '다시갈게요', '다시하겠습니다', '아니다시')


def repeats(words):
    """되풀이한 낱말·구절. 2~4낱말 구절은 사이에 3낱말까지 끼어도("제가 요청한 내용을 120%, 제가 요청한 내용을"),
    한 낱말은 바로 이어서 같거나("AI는 AI는") 앞 두 글자가 같을 때("손맛까지, 손맛이랑")."""
    w = [C.norm_text(x) for x in words]
    w = [x for x in w if x]
    hits = []

    def add(p):
        if not any(p in h for h in hits):
            hits.append(p)
    for n in (4, 3, 2):
        for i in range(len(w) - 2 * n + 1):
            for j in range(i + n, min(i + n + 4, len(w) - n + 1)):
                if w[i:i + n] == w[j:j + n]:
                    add(' '.join(w[i:i + n]))
    for a, b in zip(w, w[1:]):
        if a == b and len(a) >= 2:
            add(a)
        elif len(a) >= 3 and len(b) >= 3 and a[:2] == b[:2] and a != b:
            add(f'{a} → {b}')
    return hits


def tail_db(x, sec=0.1):
    t = x[-int(sec * SR):] if len(x) > sec * SR else x
    rms = float(np.sqrt(np.mean(t ** 2))) if len(t) else 0.0
    return 20 * np.log10(max(rms, 1e-9))


def main():
    C.setup_console()
    ap = argparse.ArgumentParser(description='남긴 문장 클립 다시 받아쓰기 검사')
    ap.add_argument('plan', help='cut_plan.py 가 만든 plan.json')
    ap.add_argument('media', help='원본(또는 마이크 파일). 컷 계획을 만든 것과 같은 파일')
    ap.add_argument('--model', default='large-v3')
    ap.add_argument('--device', default='auto', choices=['auto', 'cuda', 'cpu'])
    ap.add_argument('--lang', default='ko')
    ap.add_argument('--tail-db', type=float, default=-42.0, help='클립 끝 0.1초가 이보다 크면 끝 잘림 의심(dB)')
    a = ap.parse_args()

    C.need_ffmpeg()
    plan_path = Path(a.plan).resolve()
    plan = C.read_json(plan_path)
    segs = plan['segments'] if isinstance(plan, dict) else plan
    wav = C.extract_wav16k(a.media, plan_path.parent / 'check_audio16k.wav')
    x, sr = sf.read(str(wav), dtype='float32', always_2d=True)
    x = x.mean(1)
    model, _ = C.load_whisper(a.model, a.device)

    rows, flagged = [], 0
    for i, s in enumerate(segs, 1):
        s0, s1 = float(s['src_in']), float(s['src_out'])
        clip = x[int(s0 * SR):int(s1 * SR)]
        if len(clip) < SR * 0.2:
            continue
        out, _ = model.transcribe(np.pad(clip, (3200, 3200)), language=a.lang, beam_size=5,
                                  condition_on_previous_text=False, vad_filter=False, word_timestamps=True)
        words = [w.word for seg in out for w in (seg.words or [])]
        text = ''.join(words).strip()
        if C.is_hallucination(text):
            text, words = '', []
        notes = []
        rep = repeats(words)
        if rep:
            notes.append('반복: ' + ', '.join(f'"{r}"' for r in rep))
        n = C.norm_text(text)
        if any(r in n for r in RETAKE):
            notes.append('"다시"가 남음')
        td = tail_db(clip)
        if td > a.tail_db:
            notes.append(f'끝 잘림 의심(끝 0.1초 {td:.0f}dB)')
        want = C.norm_text(s.get('text', ''))
        if want and n:
            ratio = difflib.SequenceMatcher(None, n, want).ratio()
            if ratio < 0.7:
                notes.append(f'컷 계획 글과 다름({ratio:.0%}) — 앞뒤 말이 딸려 왔거나 빠졌을 수 있음')
        flagged += bool(notes)
        rows.append((i, s0, s1, text, notes))
        print(f'{i:>3} {C.mmss(s0)}~{C.mmss(s1)} ' + ('⚠ ' + ' · '.join(notes) if notes else 'OK'), flush=True)

    md = [f'# 컷 다시 받아쓰기 검사 — {plan_path.name}', '',
          f'클립 {len(rows)}개 중 확인 필요 {flagged}개. 강조 반복("띄우고 띄우고")은 일부러 남긴 것일 수 있다.', '',
          '| # | 원본 시각 | 다시 받아쓴 말 | 확인 |', '|---|---|---|---|']
    for i, s0, s1, text, notes in rows:
        md.append(f'| {i} | {C.mmss(s0)}~{C.mmss(s1)} | {text.replace("|", "/")} | {"⚠ " + "; ".join(notes) if notes else ""} |')
    out_md = plan_path.parent / 'check_cuts.md'
    out_md.write_text('\n'.join(md) + '\n', 'utf-8')
    print(f'검사 끝: 확인 필요 {flagged}/{len(rows)} · {out_md}')


if __name__ == '__main__':
    main()
