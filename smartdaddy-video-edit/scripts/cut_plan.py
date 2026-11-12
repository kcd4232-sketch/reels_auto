"""다시 말한 곳·긴 쉼을 찾아 컷 계획(plan.json)과 컷 목록(cuts.md)을 만듭니다.

어떻게 찾나:
  1) 소리 크기(10ms 단위)로 무음 구간(-60dB 이하, 60ms 이상)을 찾는다. 컷 경계는 항상 무음 안에 둔다.
  2) 무음으로 나뉜 말 조각마다 따로 받아쓴다. (긴 구간을 한 번에 받아쓰면 Whisper가 반복을 한 번으로 합쳐 버린다)
  3) 앞 조각이 뒤 조각의 앞부분과 같으면(= 다시 말하기) 앞 조각을 지운다.
     앞 조각 끝부분만 같으면 단어 사이 골짜기에서 그 끝부분만 지운다(앞뒤를 각각 다시 받아써서 둘 다 맞을 때만).
  4) 한 조각 안에서 같은 말을 연달아 두 번 하면 한 번으로 줄인다. 세 번 이상("띄우고 띄우고 띄우고")은 강조로 보고 남긴다.
  5) --max-pause(1.5초)보다 긴 쉼은 --keep-pause(0.6초)로 줄인다.
  6) 원칙: 애매하면 남긴다. 남은 말은 사람이 바로 지우지만, 잘린 말은 되살리기 어렵다.

결과(--out 폴더):
  plan.json   남길 구간 목록 [{src_in, src_out, text, words}] (원본 초 기준, 문장 하나 = 구간 하나)
  cuts.md     컷 목록: 지운 곳마다 원문(앞뒤 1초) → 남긴 말, 이음새 점검, 남긴 문장 목록
  frag_asr.json  조각 받아쓰기 캐시(다시 돌릴 때 빨라진다)

사용 예:
  python cut_plan.py 녹화.mp4
  python cut_plan.py 녹화.mp4 --out 편집/02_cut --max-pause 1.5 --keep-pause 0.6 --pad 0.08
  python cut_plan.py 녹화.mp4 --protect 83.2-85.0          # 일부러 두 번 말한 곳은 지우지 않기
  python cut_plan.py 녹화.mp4 --cut 120.4-121.9            # 사람이 지정한 곳 지우기(원본 초)
  python cut_plan.py 마이크.wav --out 편집/02_cut           # 게임 소리·배경음이 섞였으면 마이크 단독 파일로

알아 둘 것:
- 마이크 잡음이 커서 -60dB 무음이 거의 없으면 기준을 자동으로 올린다(--silence-db 로 직접 정할 수도 있다).
- 배경음악·게임 소리가 섞인 녹음은 무음이 없어 컷을 거의 못 찾는다. 마이크만 녹음된 파일을 주는 게 가장 좋다.
- 숫자 읽기, 세 번 이상 반복, --protect 구간은 지우지 않는다.
"""
import argparse
import difflib
import json
import re
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np
import soundfile as sf

sys.dont_write_bytecode = True      # 스킬 폴더에 __pycache__ 를 만들지 않는다
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as C  # noqa: E402

SR = 16000
VALLEY = -50          # 단어 사이 골짜기로 인정할 레벨(dB)
DEL_MARGIN = 0.25     # 지운 곳 앞뒤에 남길 무음 여유(최대)
FILLERS = {'아', '어', '음', '그', '자', '와', '오', '네', '저', '뭐', '좀', '이제', '아니', '어어', '음음', '흠', '하'}
STUTTER_PROMPT = '음, 어, 그, 자, 여기 보면, 여기 보면 이렇게 말을 반복하면 반복한 그대로 적어 주세요.'
norm = C.norm_text

# 문장 끝 판정(클립을 문장 단위로 나눌 때)
END_RE = re.compile(r'(요|다|죠|까|네|군|함|음)$')
NOT_END = ('보다', '까지', '부터', '처럼', '만큼', '니까', '는데', '아까', '지금', '먼저')


def is_sentence_end(text):
    t = (text or '').strip()
    if re.search(r'[?!]$', t):
        return True
    b = norm(t)
    if len(b) < 2 or b in FILLERS:
        return False
    if b.endswith(NOT_END):
        return False
    return bool(END_RE.search(b))


def parse_ranges(vals):
    out = []
    for v in vals or []:
        try:
            x, y = [float(z) for z in v.replace('~', '-').split('-', 1)]
        except Exception:
            C.die(f'구간 형식이 틀렸습니다: "{v}" (예: 83.2-85.0)')
        out.append((min(x, y), max(x, y), v))
    return out


class Cutter:
    def __init__(self, wav, cache_path, model, device, compute_type, lang, silence_db, min_sil, pad,
                 max_pause, keep_pause):
        x, sr = sf.read(str(wav), dtype='float32', always_2d=True)
        if sr != SR:
            C.die(f'{wav} 가 16kHz가 아닙니다.')
        self.x = x.mean(1)
        self.dur = len(self.x) / SR
        hop = SR // 100
        n = len(self.x) // hop
        r = np.sqrt((self.x[:n * hop].reshape(n, hop) ** 2).mean(1) + 1e-12)
        self.e = 20 * np.log10(r)
        floor = float(np.percentile(self.e, 5))
        if silence_db is None:
            th = -60.0
            if floor > th - 6:            # 잡음이 커서 -60dB 무음이 거의 없다
                th = min(-35.0, floor + 6)
                print(f'[안내] 바닥 잡음 {floor:.0f}dB → 무음 기준을 {th:.0f}dB로 올립니다.', flush=True)
        else:
            th = float(silence_db)
        self.th, self.floor = th, floor
        self.min_sil, self.pad, self.max_pause, self.keep_pause = min_sil, pad, max_pause, keep_pause
        self.model_name, self.device, self.compute_type, self.lang = model, device, compute_type, lang
        self._model = None
        self.cache_path = Path(cache_path)
        key = f'{model}|{lang}|{len(self.x)}|{float(np.abs(self.x[::997]).sum()):.3f}'
        self.cache = {}
        if self.cache_path.exists():
            try:
                j = json.loads(self.cache_path.read_text('utf-8'))
                if j.get('_key') == key:
                    self.cache = j.get('items', {})
            except Exception:
                pass
        self.cache_key = key
        self.asr_calls = 0
        self._sil = None

    # ── 무음 ─────────────────────────────────────────
    def silences(self):
        if self._sil is None:
            e = self.e
            sm = np.maximum.reduce([np.roll(e, k) for k in (-1, 0, 1)])
            q = sm <= self.th
            d = np.diff(np.concatenate([[0], q.astype(np.int8), [0]]))
            st, en = np.where(d == 1)[0], np.where(d == -1)[0]
            keep = (en - st) >= int(round(self.min_sil * 100))
            self._sil = np.stack([st[keep] / 100, en[keep] / 100], 1) if keep.any() else np.zeros((0, 2))
        return self._sil

    def lvl(self, t):
        i = int(t * 100)
        return float(self.e[max(0, i - 1):min(len(self.e), i + 2)].max()) if len(self.e) else -120.0

    def _ctx(self, t):
        S = self.silences()
        k = np.searchsorted(S[:, 0], t, 'right') - 1
        if k >= 0 and S[k, 0] <= t <= S[k, 1]:
            return 'sil', tuple(S[k]), None
        prev = tuple(S[k]) if k >= 0 else (t, t)
        nxt = tuple(S[k + 1]) if k + 1 < len(S) else (t, t)
        return 'voice', prev, nxt

    def _in_of(self, s, e): return round(max(s, e - min(self.pad, (e - s) / 2)), 3)
    def _out_of(self, s, e): return round(min(e, s + min(self.pad, (e - s) / 2)), 3)

    def snap_in(self, t):
        kind, p, n = self._ctx(t)
        if kind == 'sil':
            return self._in_of(*p)
        return self._in_of(*p) if t - p[1] <= n[0] - t else self._in_of(*n)

    def snap_out(self, t):
        kind, p, n = self._ctx(t)
        if kind == 'sil':
            return self._out_of(*p)
        return self._out_of(*n) if n[0] - t <= t - p[1] else self._out_of(*p)

    def speech_span(self):
        """앞뒤 무음을 뺀 실제 소리 구간."""
        S = self.silences()
        a, b = 0.0, self.dur
        if len(S) and S[0][0] <= 0.011:
            a = self._in_of(*S[0])
        if len(S) and S[-1][1] >= len(self.e) / 100 - 0.011:
            b = self._out_of(S[-1][0], self.dur)
        return a, b

    # ── 받아쓰기 ─────────────────────────────────────
    def model(self):
        if self._model is None:
            self._model, _ = C.load_whisper(self.model_name, self.device, self.compute_type)
        return self._model

    def _transcribe(self, x, offset):
        prompt = STUTTER_PROMPT if self.lang == 'ko' else None
        segs, _ = self.model().transcribe(x, language=self.lang, beam_size=5, condition_on_previous_text=False,
                                          vad_filter=False, word_timestamps=True, initial_prompt=prompt)
        words = [[round(offset + w.start, 3), round(offset + w.end, 3), w.word] for s in segs for w in (s.words or [])]
        text = ''.join(w[2] for w in words).strip()
        if C.is_hallucination(text, prompt or ''):
            text, words = '', []       # 무음·잡음에서 나온 환각
        self.asr_calls += 1
        if self.asr_calls % 25 == 0:
            print(f'  조각 받아쓰기 {self.asr_calls}회', flush=True)
        return dict(text=text, words=words)

    def asr(self, a, b):
        """[a, b] 구간 받아쓰기 + 단어 시각(원본 초). 캐시."""
        a, b = round(a, 3), round(b, 3)
        key = f'{a:.3f}-{b:.3f}'
        if key in self.cache:
            return self.cache[key]
        if b - a < 0.05:
            return dict(text='', words=[])
        pad = 0.2
        x = self.x[int(a * SR):int(b * SR)]
        x = np.pad(x, (int(pad * SR), int(pad * SR)))
        r = self._transcribe(x, a - pad)
        self.cache[key] = r
        if len(self.cache) % 40 == 0:
            self.save()
        return r

    def asr_audio(self, x, key):
        if key in self.cache:
            return self.cache[key]
        r = self._transcribe(np.pad(x, (3200, 3200)), 0.0)
        self.cache[key] = r
        return r

    def save(self):
        self.cache_path.write_text(json.dumps(dict(_key=self.cache_key, items=self.cache), ensure_ascii=False), 'utf-8')

    # ── 다시 말하기 판정 ───────────────────────────────
    @staticmethod
    def is_filler(t): return len(norm(t)) <= 1 or norm(t) in FILLERS

    @staticmethod
    def lcp(x, y):
        n = 0
        while n < min(len(x), len(y)) and x[n] == y[n]:
            n += 1
        return n

    def restart(self, X, Y):
        """X(앞에서 한 말 전체)를 Y(뒤에서 다시 한 말)로 대체할 수 있으면 True."""
        if len(X) < 2 or len(Y) < 2:
            return False
        if Y.startswith(X):
            return True
        L = self.lcp(X, Y)
        if L >= 3 and L >= 0.6 * len(X):
            return True
        if L >= 8:                    # 8글자 넘게 똑같이 시작하면 다시 말한 것
            return True
        if len(X) >= 4 and difflib.SequenceMatcher(None, X, Y[:len(X)]).ratio() >= 0.8:
            return True
        if L >= 2 and len(X) >= 4:
            W = Counter(Y[:int(len(X) * 2.5)])
            Cx = Counter(X)
            if sum(min(c, W[ch]) for ch, c in Cx.items()) / len(X) >= 0.85:
                return True
        return False

    def suffix_restart(self, X, Y):
        """X 끝부분 = Y 앞부분이면 그 길이(글자), 아니면 0."""
        top = min(len(X) - 1, len(Y), 30)
        for L in range(top, 3, -1):
            if X[-L:] == Y[:L]:
                return L
        for L in range(top, 5, -1):
            if difflib.SequenceMatcher(None, X[-L:], Y[:L]).ratio() >= 0.85:
                return L
        for p in range(1, len(X) - 2):          # 같은 말로 다시 시작했는데 앞 시도 끝이 웅얼거림
            if X[p:p + 3] == Y[:3]:
                c = self.lcp(X[p:], Y)
                if c >= 3 and (len(X) - p) - c <= 3:
                    return len(X) - p
        return 0

    def valleys(self, fa, fb):
        """조각 안 단어 사이 골짜기 후보(시각)."""
        e = self.e
        i0, i1 = int((fa + 0.12) * 100), int((fb - 0.08) * 100)
        out = []
        for k in range(max(0, i0), min(len(e), i1)):
            if e[k] <= VALLEY + 4 and e[k] == e[max(0, k - 4):k + 5].min():
                out.append(k / 100 + 0.005)
        return out

    def find_cut(self, fa, fb, head, tail):
        """조각 [fa,fb]를 head(남김) | tail(삭제)로 가를 컷 시각. 앞·뒤를 각각 다시 받아써서 둘 다 맞는 골짜기 중 가장 깊은 곳."""
        cand = []
        for v in self.valleys(fa, fb):
            h = norm(self.asr(fa, v)['text'])
            t = norm(self.asr(v, fb)['text'])
            rh = difflib.SequenceMatcher(None, h, head).ratio()
            rt = difflib.SequenceMatcher(None, t, tail).ratio()
            if rh >= 0.75 and rt >= 0.6:
                cand.append((rh + rt, float(self.e[int(v * 100)]), v))
        if not cand:
            return None
        top = max(c[0] for c in cand)
        return min((c for c in cand if c[0] >= top - 0.15), key=lambda c: c[1])[2]

    def inner_repeats(self, fs, fe, W):
        """조각 안 같은 말 연달아(1~3어절) → [(c1, c2, 설명)]. c1=None이면 조각 처음부터 c2까지 삭제.
        세 번 이상 반복과 숫자는 강조·읽기로 보고 남긴다. 컷은 앞뒤 받아쓰기가 둘 다 맞을 때만."""
        out = []
        nw = [norm(w[2]) for w in W]
        i = 0
        last_c2 = fs
        while i < len(W):
            hit = None
            for n in (3, 2, 1):
                if i + 2 * n > len(W):
                    continue
                A, B = ''.join(nw[i:i + n]), ''.join(nw[i + n:i + 2 * n])
                if len(A) < 2 or A.isdigit():
                    continue
                if not (A == B or (B.startswith(A) and len(B) - len(A) <= 2)
                        or (len(A) >= 4 and difflib.SequenceMatcher(None, A, B).ratio() >= 0.8)):
                    continue
                if ''.join(nw[i + 2 * n:i + 3 * n]) == A:
                    continue            # 세 번 반복은 남김
                if i > 0 and ''.join(nw[max(0, i - n):i]) == A:
                    continue            # 이미 반복 중
                hit = n
                break
            if not hit:
                i += 1
                continue
            n = hit
            full_i, full_n = ''.join(nw[i:]), ''.join(nw[i + n:])
            head_i, head_n = ''.join(nw[:i]), ''.join(nw[:i + n])

            def score(v, tail, head):
                t = norm(self.asr(v, fe)['text'])
                r1 = difflib.SequenceMatcher(None, t, tail).ratio()
                if not head:
                    return r1, r1
                h = norm(self.asr(fs, v)['text'])
                r2 = difflib.SequenceMatcher(None, h, head).ratio()
                return r1 + r2, min(r1, r2)

            def pick(t0, tail, head):
                cand = []
                for v in self.valleys(max(last_c2, fs), fe):
                    if not (t0 - 0.25 <= v <= t0 + 0.6):
                        continue
                    sc, mn = score(v, tail, head)
                    if mn >= 0.75:
                        cand.append((sc, float(self.e[int(v * 100)]), v))
                if not cand:
                    return None
                top = max(c[0] for c in cand)
                return min((c for c in cand if c[0] >= top - 0.1), key=lambda c: c[1])[2]

            c1 = pick(W[i][0], full_i, head_i) if i > 0 else None
            c2 = pick(W[i + n][0], full_n, head_n)
            ok = c2 is not None and (i == 0 or (c1 is not None and c1 < c2 - 0.1))
            if ok:
                gone = norm(self.asr(c1 if c1 else fs, c2)['text'])
                ok = (difflib.SequenceMatcher(None, gone, ''.join(nw[i:i + n])).ratio() >= 0.6
                      or (i == 0 and len(gone) <= len(''.join(nw[:n])) + 1))
            if ok:
                out.append((c1, c2, ' '.join(w[2].strip() for w in W[i:i + n]) + ' (반복)'))
                last_c2 = c2
                i += n
            else:
                i += 1
        return out

    # ── 조각 정밀화(핵심) ───────────────────────────────
    def refine(self, a, b, protect=()):
        S = self.silences()
        inner = [tuple(s) for s in S if s[0] > a + 0.02 and s[1] < b - 0.02]
        edges = [a] + [x for s in inner for x in s] + [b]
        frs = [[edges[2 * n], edges[2 * n + 1]] for n in range(len(edges) // 2)]
        gaps = inner
        print(f'말 조각 {len(frs)}개 · 무음 기준 {self.th:.0f}dB', flush=True)
        R = [self.asr(max(a, fa - 0.05), min(b, fb + 0.05)) if fb - fa >= 0.12 else dict(text='', words=[]) for fa, fb in frs]
        T = [r['text'] for r in R]
        keep = [True] * len(frs)
        why = [''] * len(frs)
        trim = {}
        n = 0
        while n < len(frs) - 1:
            if self.is_filler(T[n]):
                n += 1
                continue
            hit = None
            lead = ''                  # 앞머리 군말("자, 이")은 비교에서 뺀다
            for w in R[n]['words']:
                z = norm(w[2])
                if z and (z in FILLERS or len(z) <= 1):
                    lead += z
                    continue
                if z:
                    break
            cnt = 0
            for m in range(n + 1, len(frs)):
                if frs[m][0] - frs[n][1] > 12:
                    break
                if self.is_filler(T[m]):
                    continue          # 숨소리·잡음 조각은 건너뛰고 말 조각 3개까지 본다
                cnt += 1
                if cnt > 3:
                    break
                k = m
                while k > n + 1 and self.is_filler(T[k - 1]):
                    k -= 1
                X = norm(''.join(T[n:k]))
                Y = norm(''.join(T[m:m + 6]))
                if len(X) > 40:
                    break
                X2 = X[len(lead):] if lead and X.startswith(lead) else X
                if self.restart(X, Y) or (X2 != X and self.restart(X2, Y)):
                    hit = ('full', m)
                    break
                L = self.suffix_restart(X, Y)
                if L:
                    off = len(X) - L
                    bounds = []
                    pos = 0
                    for q in range(n, k):
                        for wi, w in enumerate(R[q]['words']):
                            bounds.append((pos, q, wi))
                            pos += len(norm(w[2]))
                    found = next(((q, wi, p) for d in (0, 1, -1) for p, q, wi in bounds if p == off + d), None)
                    if found:
                        q, wi, p = found
                        if wi == 0:
                            hit = ('full_from', m, q)
                            break
                        head = norm(''.join(w[2] for w in R[q]['words'][:wi]))
                        tail = norm(''.join(w[2] for w in R[q]['words'][wi:]))
                        v = self.find_cut(frs[q][0] - 0.05, frs[q][1] + 0.05, head, tail)
                        if v:
                            hit = ('trim', m, q, v)
                            break
                        if len(head) <= 2:
                            hit = ('full_from', m, q)
                            break
            if hit:
                if hit[0] == 'full':
                    lo, m = n, hit[1]
                elif hit[0] == 'full_from':
                    lo, m = hit[2], hit[1]
                else:
                    _, m, q, v = hit
                    trim[q] = v
                    why[q] = f'끝부분 다시 말하기 → "{T[m][:24]}"'
                    lo = q + 1
                for q in range(lo, m):
                    keep[q] = False
                    why[q] = f'다시 말하기 → "{T[m][:24]}"'
                n = m
            else:
                n += 1
        holes = {}
        for q in range(len(frs)):
            if not keep[q] or not R[q]['words']:
                continue
            hs = self.inner_repeats(frs[q][0] - 0.05, min(frs[q][1] + 0.05, trim.get(q, 1e9)),
                                    [w for w in R[q]['words'] if w[0] < trim.get(q, 1e9)])
            if hs:
                holes[q] = hs
        # 긴 쉼 속 짧은 잡음(글자 없음, 0.35초 미만)은 쉼의 일부로 보고 지운다
        speech = [bool(norm(T[q])) or (fb - fa) >= 0.35 for q, (fa, fb) in enumerate(frs)]
        soft = set()
        for q, (fa, fb) in enumerate(frs):
            if speech[q] or not keep[q]:
                continue
            p = next((i for i in range(q - 1, -1, -1) if speech[i] and keep[i]), None)
            nx = next((i for i in range(q + 1, len(frs)) if speech[i] and keep[i]), None)
            left = frs[p][1] if p is not None else a
            right = frs[nx][0] if nx is not None else b
            if right - left > self.max_pause or p is None or nx is None:
                keep[q] = False
                soft.add(q)
        for q, (fa, fb) in enumerate(frs):          # 보호 구간은 자동 삭제 취소
            if any(fa < y and fb > x for x, y, *_ in protect):
                keep[q] = True
                soft.discard(q)
                why[q] = ''
                trim.pop(q, None)
                holes.pop(q, None)
        # 남길 구간: (시작, 끝, 시작종류, 끝종류, 조각번호). 'f'=무음 경계, 'c'=골짜기 컷
        spans = []
        for q in range(len(frs)):
            if not keep[q]:
                continue
            st, sk = frs[q][0], 'f'
            en, ek = (trim[q], 'c') if q in trim else (frs[q][1], 'f')
            for c1, c2, _ in holes.get(q, []):
                if c1 is not None:
                    spans.append([st, c1, sk, 'c', q])
                st, sk = c2, 'c'
            spans.append([st, en, sk, ek, q])
        half = self.keep_pause / 2
        subs = []
        for sp in spans:
            st, en, sk, ek, q = sp
            if subs:
                ps = subs[-1]
                if ps[3] == 'f' and sk == 'f' and ps[4] == q - 1:      # 이웃 조각, 사이는 무음
                    gs, ge = gaps[q - 1]
                    if ge - gs <= self.max_pause:
                        ps[1], ps[3], ps[4] = en, ek, q
                        continue
                    ps[1] = gs + half                                   # 긴 쉼 줄이기
                    subs.append([ge - half, en, 'x', ek, q])
                    continue
                if ps[3] == 'f':                                        # 앞 구간 닫기
                    pq = ps[4]
                    gs, ge = gaps[pq]
                    mg = half if all(i in soft for i in range(pq + 1, q)) else DEL_MARGIN
                    ps[1] = min(ge, gs + min(mg, (ge - gs) / 2))
            if sk == 'f':
                if q == 0:
                    st = a
                else:
                    gs, ge = gaps[q - 1]
                    pq = subs[-1][4] if subs else -1
                    mg = half if all(i in soft for i in range(pq + 1, q)) else DEL_MARGIN
                    st = max(gs, ge - min(mg, (ge - gs) / 2))
            subs.append([st, en, 'x', ek, q])
        if subs and subs[-1][3] == 'f' and subs[-1][4] == len(frs) - 1:
            subs[-1][1] = b
        elif subs and subs[-1][3] == 'f':
            pq = subs[-1][4]
            gs, ge = gaps[pq]
            mg = half if all(i in soft for i in range(pq + 1, len(frs))) else DEL_MARGIN
            subs[-1][1] = min(ge, gs + min(mg, (ge - gs) / 2))
        out = []
        for st, en, *_ in subs:
            if en - st < 0.12:
                continue
            txt = self.asr(st, en)['text']
            if not norm(txt) and en - st < 1.0:
                continue         # 말 없는 짧은 조각(숨소리) 버림
            out.append([round(st, 3), round(en, 3)])
        frags = [dict(a=round(fa, 3), b=round(fb, 3), text=t, keep=k, why=w or ('쉼 속 잡음' if q in soft else ''),
                      trim=trim.get(q), holes=holes.get(q, []))
                 for q, ((fa, fb), t, k, w) in enumerate(zip(frs, T, keep, why))]
        return out, frags, gaps

    # ── 문장 단위로 나누기 ──────────────────────────────
    def split_sentences(self, spans, frags, gaps):
        """한 구간 안에서 문장이 끝나고 쉬는 곳(무음)마다 나눈다. 시간은 빼지 않는다(앞 클립 끝 = 뒤 클립 시작)."""
        end_at = {round(f['b'], 3): f for f in frags}
        out = []
        for st, en in spans:
            cur = st
            for gs, ge in gaps:
                if not (gs > cur + 0.6 and ge < en - 0.6):
                    continue
                if ge - gs < 0.12:
                    continue
                f = end_at.get(round(gs, 3))
                if not f or not f['keep'] or f['trim'] or not is_sentence_end(f['text']):
                    continue
                mid = round((gs + ge) / 2, 3)
                out.append([cur, mid])
                cur = mid
            out.append([cur, en])
        return out


def subtract(spans, cuts):
    out = []
    for x, y in spans:
        pcs = [(x, y)]
        for c1, c2, *_ in cuts:
            nx = []
            for p, q in pcs:
                if c2 <= p or c1 >= q:
                    nx.append((p, q))
                    continue
                if c1 > p:
                    nx.append((p, c1))
                if c2 < q:
                    nx.append((c2, q))
            pcs = nx
        out += [[round(p, 3), round(q, 3)] for p, q in pcs if q - p >= 0.12]
    return out


def main():
    C.setup_console()
    ap = argparse.ArgumentParser(description='다시 말하기·긴 쉼 컷 계획')
    ap.add_argument('media', help='영상 또는 음성(마이크 단독 파일이면 가장 정확)')
    ap.add_argument('--out', help='결과 폴더(기본: 원본 옆 <이름>_edit)')
    ap.add_argument('--max-pause', type=float, default=1.5, help='이보다 긴 쉼은 줄인다(초)')
    ap.add_argument('--keep-pause', type=float, default=0.6, help='줄인 쉼의 길이(초)')
    ap.add_argument('--pad', type=float, default=0.08, help='말 앞뒤에 남길 최소 여유(초, 무음 안)')
    ap.add_argument('--silence-db', type=float, default=None, help='무음 기준 dB(기본 -60, 잡음이 크면 자동 조정)')
    ap.add_argument('--min-silence', type=float, default=0.06, help='무음으로 칠 최소 길이(초)')
    ap.add_argument('--protect', action='append', help='지우지 않을 원본 구간 "시작-끝"(초). 여러 번 쓸 수 있음')
    ap.add_argument('--cut', action='append', help='사람이 지정해 지울 원본 구간 "시작-끝"(초). 여러 번 쓸 수 있음')
    ap.add_argument('--model', default='large-v3')
    ap.add_argument('--device', default='auto', choices=['auto', 'cuda', 'cpu'])
    ap.add_argument('--compute-type', default=None)
    ap.add_argument('--lang', default='ko')
    a = ap.parse_args()

    C.need_ffmpeg()
    media = Path(a.media).resolve()
    if not media.exists():
        C.die(f'파일이 없습니다: {media}')
    if not C.media_info(media)['has_audio']:
        C.die('소리 트랙이 없는 파일입니다.')
    out = Path(a.out).resolve() if a.out else C.default_workdir(media)
    out.mkdir(parents=True, exist_ok=True)
    wav = C.extract_wav16k(media, out / 'audio16k.wav')
    protect = parse_ranges(a.protect)
    manual = parse_ranges(a.cut)
    t0 = time.time()
    cu = Cutter(wav, out / 'frag_asr.json', a.model, a.device, a.compute_type, a.lang, a.silence_db, a.min_silence,
                a.pad, a.max_pause, a.keep_pause)
    S = cu.silences()
    sil_total = float((S[:, 1] - S[:, 0]).sum()) if len(S) else 0.0
    if cu.dur > 20 and sil_total < cu.dur * 0.03:
        print('[주의] 무음 구간이 거의 없습니다. 배경음·게임 소리가 섞였다면 마이크만 녹음된 파일로 다시 해 주세요.', flush=True)
    A, B = cu.speech_span()
    if B - A < 0.3:
        C.die('말소리를 찾지 못했습니다(전부 무음).')
    spans, frags, gaps = cu.refine(A, B, protect)
    spans = subtract(spans, manual)
    spans = cu.split_sentences(spans, frags, gaps)
    segs = []
    for st, en in spans:
        r = cu.asr(st, en)
        segs.append(dict(src_in=st, src_out=en, text=r['text'], words=r['words']))

    # ── 지운 곳 분류 ───────────────────────────────────
    removed = []
    cur = A
    edges = [(s['src_in'], s['src_out']) for s in segs] + [(B, B)]
    for k, (st, en) in enumerate(edges):
        if st - cur > 0.03:
            c0, c1 = cur, st
            fr = [f for f in frags if f['a'] < c1 - 0.02 and f['b'] > c0 + 0.02]
            reason, text = '', ''
            gone = [f for f in fr if not f['keep'] and f['why'] != '쉼 속 잡음']
            tr = [f for f in fr if f['trim'] and f['trim'] < c1]
            hl = [h for f in fr for h in f['holes'] if (h[0] or f['a']) < c1 and h[1] > c0]
            mc = [m for m in manual if m[0] < c1 and m[1] > c0]
            if gone:
                reason = gone[0]['why'] or '다시 말하기'
            elif tr:
                reason = tr[0]['why']
            elif hl:
                reason = '조각 안 반복: ' + hl[0][2]
            elif mc:
                reason = f'사람 지정 컷({mc[0][2]})'
            elif not fr or all(not norm(f['text']) or f['why'] == '쉼 속 잡음' for f in fr):
                reason = '긴 쉼 줄임' if st < B else '끝 무음'
            else:
                reason = '말 없는 짧은 소리(숨·잡음)'
            if reason != '긴 쉼 줄임':
                if gone and not tr and not hl:     # 조각째 지운 곳: 조각 받아쓰기를 그대로(판정 근거)
                    text = ' '.join(f['text'] for f in gone if norm(f['text']))
                else:
                    text = cu.asr(c0, c1)['text'] if c1 - c0 >= 0.12 else ''
            removed.append(dict(src_in=round(c0, 3), src_out=round(c1, 3), reason=reason, text=text, after_seg=k))
        cur = max(cur, en)

    # ── 이음새 점검(원문 앞뒤 1초 → 남긴 말) ────────────────
    tl = []
    pos = 0.0
    for s in segs:
        tl.append(pos)
        pos += s['src_out'] - s['src_in']
    total = pos

    def edited_audio(t_a, t_b):
        parts = []
        for s, p in zip(segs, tl):
            lo, hi = max(t_a, p), min(t_b, p + s['src_out'] - s['src_in'])
            if hi > lo:
                o = s['src_in'] + (lo - p)
                parts.append(cu.x[int(o * SR):int((o + hi - lo) * SR)])
        return np.concatenate(parts) if parts else np.zeros(1, np.float32)

    def repeats(t):
        w = [norm(z) for z in t.split() if norm(z)]
        res = []
        for n in (3, 2, 1):
            for i in range(len(w) - 2 * n + 1):
                x, y = ''.join(w[i:i + n]), ''.join(w[i + n:i + 2 * n])
                if len(x) >= 2 and (x == y or (len(x) >= 4 and difflib.SequenceMatcher(None, x, y).ratio() >= 0.8)):
                    if ''.join(w[i + 2 * n:i + 3 * n]) != x:
                        res.append(' '.join(w[i:i + 2 * n]))
        return res

    for r in removed:
        k = r['after_seg']
        if k == 0 or k >= len(segs):
            r.update(seam_at=None, original='', kept='', flags=[])
            continue
        at = tl[k]
        r['seam_at'] = round(at, 3)
        flags = []
        if r['reason'] != '긴 쉼 줄임':
            c0, c1 = r['src_in'], r['src_out']
            if c1 - c0 <= 5:
                r['original'] = cu.asr(max(0, c0 - 1), min(cu.dur, c1 + 1))['text']
            else:                       # 긴 구간은 한 번에 받아쓰면 Whisper가 반복을 합쳐 버린다
                r['original'] = (f'{cu.asr(max(0, c0 - 1), c0)["text"]} ‖ (지운 {c1 - c0:.1f}초) ‖ '
                                 f'{cu.asr(c1, min(cu.dur, c1 + 1))["text"]}')
            r['kept'] = cu.asr_audio(edited_audio(at - 1, at + 1), f'seam:{segs[k - 1]["src_out"]:.3f}:{segs[k]["src_in"]:.3f}')['text']
            rp = repeats(r['kept'])
            if rp:
                flags.append('이음새 반복? ' + ' / '.join(rp[:2]))
        else:
            r['original'] = r['kept'] = ''
        lo, li = cu.lvl(segs[k - 1]['src_out']), cu.lvl(segs[k]['src_in'])
        if lo > -50:
            flags.append(f'앞 클립 끝 {lo:.0f}dB(단어 사이 컷 · 들어서 확인)')
        if li > -50:
            flags.append(f'뒤 클립 시작 {li:.0f}dB(단어 사이 컷 · 들어서 확인)')
        r['flags'] = flags
    cu.save()

    plan = dict(version=1, media=media.as_posix(), duration=round(cu.dur, 3), edited_duration=round(total, 3),
                params=dict(max_pause=a.max_pause, keep_pause=a.keep_pause, pad=a.pad, silence_db=round(cu.th, 1),
                            min_silence=a.min_silence, protect=[p[2] for p in protect], cut=[m[2] for m in manual],
                            model=a.model),
                segments=segs, removed=removed)
    C.write_json(out / 'plan.json', plan)
    C.write_json(out / 'frags.json', frags)          # 조각별 판정(점검용)

    # ── cuts.md ─────────────────────────────────────────
    mm = C.mmss
    pauses = [r for r in removed if r['reason'] == '긴 쉼 줄임']
    talks = [r for r in removed if r['reason'] not in ('긴 쉼 줄임', '끝 무음')]
    flagged = [r for r in removed if r.get('flags')]
    L = [f'# 컷 목록 · {media.name}', '',
         f'- 원본 {mm(cu.dur)} → 편집 {mm(total)} (문장 클립 {len(segs)}개)',
         f'- 지운 말 {len(talks)}곳 · 줄인 쉼 {len(pauses)}곳({sum(r["src_out"] - r["src_in"] for r in pauses):.1f}초 줄임)',
         f'- 무음 기준 {cu.th:.0f}dB(바닥 잡음 {cu.floor:.0f}dB) · 쉼 {a.max_pause}초 초과 → {a.keep_pause}초',
         '- 시각은 모두 **원본** 기준. 되살리려면 CapCut에서 앞 클립 끝을 끌어 늘리거나(클립이 원본 전체를 참조),'
         ' `--protect 시작-끝`으로 다시 만든다.', '']
    if flagged:
        L += ['## 확인 필요', ''] + [f'- 원본 {mm(r["src_in"])} · ' + '; '.join(r['flags']) for r in flagged] + ['']
    L += ['## 지운 말 (원문 앞뒤 1초 → 남긴 말)', '']
    if not talks:
        L.append('- 없음')
    for r in talks:
        L.append(f'- **원본 {mm(r["src_in"])}~{mm(r["src_out"])}** ({r["src_out"] - r["src_in"]:.2f}초) {r["reason"]}')
        if r['text']:
            L.append(f'  - 지운 말: "{r["text"]}"')
        if r.get('original'):
            L.append(f'  - 원문({mm(max(0, r["src_in"] - 1))}~{mm(r["src_out"] + 1)}): {r["original"]}')
        if r.get('seam_at') is not None:
            L.append(f'  - 남긴 말(편집 {mm(max(0, r["seam_at"] - 1))}~{mm(r["seam_at"] + 1)}): {r.get("kept", "")}')
    L += ['', '## 줄인 쉼', '']
    L += [f'- 원본 {mm(r["src_in"])}~{mm(r["src_out"])} ({r["src_out"] - r["src_in"]:.1f}초 뺌)' for r in pauses] or ['- 없음']
    L += ['', '## 남긴 문장(클립) 목록', '']
    for s, p in zip(segs, tl):
        L.append(f'- `편집 {mm(p)}` 원본 {mm(s["src_in"])}~{mm(s["src_out"])} ({s["src_out"] - s["src_in"]:.1f}초) {s["text"]}')
    (out / 'cuts.md').write_text('\n'.join(L) + '\n', 'utf-8')
    print(f'완료 {time.time() - t0:.0f}초 · 원본 {mm(cu.dur)} → 편집 {mm(total)} · 클립 {len(segs)}개 · 지운 말 {len(talks)}곳 · 줄인 쉼 {len(pauses)}곳 · 확인 필요 {len(flagged)}곳')
    print(f'  {out / "plan.json"}\n  {out / "cuts.md"}')


if __name__ == '__main__':
    main()
