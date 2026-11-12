"""컷 계획(plan.json)으로 CapCut 프로젝트(초벌)를 조립합니다.

- 메인 트랙: 남긴 구간을 순서대로 이어 붙인다. 문장 하나 = 클립 하나.
  각 클립은 원본 파일 '전체'를 참조하므로 CapCut에서 클립 가장자리를 끌어 지운 부분을 되살리거나 더 줄일 수 있다.
- --voice 로 마이크 파일을 따로 주면 보이스 트랙도 같은 방식(문장 클립 + 원본 전체 참조)으로 깔고 영상 소리는 끈다.
- --subtitles: 단어 시각(words.json)으로 의미 단위 자막을 만든다. CapCut 네이티브 텍스트 클립 + 같은 내용의 SRT 파일.
  (꾸밈말·관형어 뒤에서 끊지 않음, 문장 끝·쉼표·연결어미·주어/목적어 조사 뒤에서 끊음, 한 줄 30자 남짓, 시작 = 목소리 + 0.15초)
- --script 대본.md: 자막 글자를 대본 표기로 맞춘다(받아쓰기와 대본을 글자 단위로 맞춰 봄). "채찌피티"→"챗GPT",
  "삼십 시간"→"30시간"처럼 받아쓰기 오류와 숫자 표기가 대본대로 나온다. 대본에 없는 즉흥 멘트는 받아쓰기 그대로 둔다.
  *[화면 신호]*, [대괄호], # 제목 줄은 읽지 않는 것으로 보고 뺀다.
- --overlays 덧입히기.json: 효과음·줌·모션 카드·강조 글자·배경음을 각각 따로 클립으로 얹는다(아래 '덧입히기 형식').
- 템플릿: 사용자가 실제로 쓰던 CapCut 프로젝트 하나. 그 프로젝트의 클립·재료 형식(자막 글꼴·크기·위치 포함)을 복제하고
  내용은 비운다. 템플릿 프로젝트는 읽기만 하고 절대 고치지 않는다.
  템플릿에 있어야 하는 것: 영상 클립 1개 이상, 로컬 파일 오디오 클립 1개(보이스/음성 파일·효과음을 쓸 때), 텍스트 클립 1개(자막·강조 글자를 쓸 때).

결과:
  <스테이징 폴더>/<새 이름>/     CapCut 프로젝트 폴더(아직 CapCut에 등록 안 됨)
  <스테이징 폴더>/<새 이름>.srt   자막 파일(--subtitles)
  <스테이징 폴더>/<새 이름>_timeline.json   편집 시각 ↔ 원본 시각 대응표, 덧입힌 것 목록(피드백 반영용)

사용 예:
  python capcut_build.py --template "내 평소 프로젝트" --plan 편집/02_cut/plan.json --media 녹화.mp4 --name "초벌_v001" --subtitles
  python capcut_build.py --template "내 평소 프로젝트" --plan plan.json --media 화면.mp4 --voice 마이크.wav --name "초벌_v002"
  python capcut_build.py ... --subtitles --script 대본.md --overlays 편집/overlays.json --name "초벌_v003"
  python capcut_build.py ... --name "초벌_v001" --install      # CapCut을 끈 뒤에, 사용자 허락을 받고 등록

덧입히기 형식(overlays.json — 목록 하나, 또는 {"items": [...]}). 시각은 셋 중 하나로 정한다:
  "at": 편집본 초 · "src": 원본 초(잘린 곳이면 다음 클립 시작으로) · "word": "실제로 말한 낱말"(받아쓰기에서 찾음,
  "near": 편집본 초 근처에서, "nth": 몇 번째) — 장면 박자는 대본이 아니라 실제로 말한 낱말에 맞춘다.
  길이는 "dur"(초) 또는 "end"/"end_src"/"end_word". "offset": 시작을 이만큼 옮김(초).
  {"type": "sfx",    "word": "결과는", "file": "sfx/snap.wav", "db": -20, "from": 0.0, "dur": 1.2}
  {"type": "zoom",   "at": 12.0, "dur": 3.0, "scale": 1.4, "x": 0.25, "y": 0.8, "ramp": 0.3, "out": "smooth"}
       x, y = 확대할 곳(화면 왼쪽 위 0,0 ~ 오른쪽 아래 1,1). 원본 위 '줌' 트랙에 얹으므로 지우면 원래 화면.
       "out": "cut"이면 줌이 풀리지 않은 채 끝나며 원래 화면으로 바로 돌아온다.
  {"type": "motion", "at": 30.5, "file": "편집/motion/time.mp4", "fade": 0.2}      길이 생략 = 파일 길이
  {"type": "text",   "word": "마동석", "dur": 1.5, "text": "마동석?!", "x": 0.5, "y": 0.5, "size": 1.6}
       템플릿 텍스트 스타일(사용자 글꼴·테두리)로 화면 가운데에 강조 글자. size = 템플릿 글자 크기 배수.
  {"type": "bgm",    "at": 0, "end": 45.0, "file": "music.mp3", "db": -40}         모자라면 반복해서 채운다
  어떤 항목이든 "note": "왜 넣었는지"를 적어 두면 _timeline.json 에 같이 남는다.

설치(--install) 규칙: CapCut이 켜져 있으면 거부, 같은 이름 프로젝트가 있으면 거부(새 이름으로 만들 것),
root_meta_info.json(프로젝트 목록)을 백업하고 기존 항목은 그대로 둔 채 맨 앞에 새 항목만 추가.
프로젝트는 임시 폴더에 복사·검증한 뒤 새 이름으로 옮기고 목록을 기록한다. 실패하면 안전하게 확인되는 변경만 자동 복구한다.

피해 가는 함정:
- 오디오 재료는 로컬 파일 형식(extract_music). 라이브러리 소리(effect_id 있음)를 복제하면 CapCut이 열 때 소리를 바꿔 버린다.
- 템플릿 클립의 키프레임·애니메이션은 지운다(영상 클립 키프레임 time_offset은 원본 시각 기준 = source start 포함).
- 트랙 안 클립은 시작 시각 순으로 정렬해 저장한다.
"""
import argparse
import copy
import difflib
import hashlib
import json
import os
import re
import shutil
import sys
import time
import uuid
from pathlib import Path

sys.dont_write_bytecode = True      # 스킬 폴더에 __pycache__ 를 만들지 않는다
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as C  # noqa: E402

MARKER = '_staging_by_capcut_build.txt'
LEAD = 0.15        # 자막 시작 = Whisper 단어 시작 + 0.15초(목소리 시작에 맞춤)
TAIL = 0.20        # 자막 끝 = 마지막 단어 끝 + 0.2초
MAXC, HARD = 30, 36
ONE_LINE = 34      # 한 문장이 이 글자 수 이하면 나누지 않는다


def uid():
    return str(uuid.uuid4()).upper()


def kf(prop, pts):
    """키프레임 묶음. pts = [(time_offset us, 값)]. 영상 클립의 time_offset은 원본 시각 기준(source start 포함)."""
    return dict(id=uid(), material_id='', property_type=prop, keyframe_list=[
        dict(id=uid(), curveType='Line', time_offset=int(t), left_control=dict(x=0.0, y=0.0), right_control=dict(x=0.0, y=0.0),
             values=[round(v, 5)], string_value='', graphID='') for t, v in pts])


# ── 자막: 의미 단위 나누기 ─────────────────────────────
FILLER = {'어', '음', '아', '흠', '호', '흐', '으', '엄', '어어', '음음', '으음'}
NEVER = {'잘', '좀', '더', '되게', '진짜', '너무', '다', '꽤', '조금', '가장', '아주', '정말', '막', '그냥', '이렇게', '저렇게', '그렇게',
         '이런', '그런', '저런', '이', '그', '저', '한', '두', '세', '네', '제', '내', '약간', '특히', '바로', '먼저', '자', '와', '아', '오', '야',
         '또', '역시', '이제', '일단', '여기', '거의', '훨씬', '확실히', '어떤', '무슨', '모든', '각', '몇', '첫', '다른', '같은', '새', '옛'}
# 관형어(뒤 명사를 꾸미는 말): 이 뒤에서는 끊지 않는다("철권 같은 / 3D 게임" 금지)
ATTR_END = ('하는', '되는', '있는', '없는', '않는', '같은', '다른', '어떤', '이런', '그런', '저런', '던', '좋은', '많은', '작은', '높은',
            '낮은', '싶은', '받은', '만든', '만드는', '나오는', '보는', '주는', '가는', '오는', '쓰는', '먹는', '아는', '모르는', '하신', '되신')
NOT_END = ('보다', '까지', '부터', '처럼', '만큼', '니까', '는데', '아까', '지금', '먼저')


def bare(t):
    return re.sub(r'[.,?!…~]+$', '', t)


def is_end(t):
    if re.search(r'[.?!]$', t):
        return True
    b = bare(t)
    if len(b) < 2 or b in NEVER or b.endswith(NOT_END):
        return False
    return bool(re.search(r'(요|다|죠|까|네)$', b))


def score(t):
    """이 말 뒤에서 끊기 좋은 정도(0=끊지 않음)."""
    b = bare(t)
    if b in NEVER or len(b) < 2 or b.endswith(ATTR_END):
        return 0
    if t.endswith(','):
        return 3
    if b.endswith(('는데', '지만', '니까', '어서', '아서', '해서', '하고', '이고', '면서', '거든요', '는데요')):
        return 3
    if re.search(r'(고|며|면|서)$', b):
        return 2.5
    if b.endswith(('에서', '으로', '한테', '에게', '이랑', '보다')):
        return 1.6
    if re.search(r'(은|는|이|가|을|를|로|에|과|와|랑|도)$', b):
        return 1.5
    return 0


def clen(ws):
    return len(' '.join(x[2] for x in ws))


def split_long(st):
    if clen(st) <= MAXC:
        return [st]
    best = None
    for k in range(1, len(st)):
        l, r = clen(st[:k]), clen(st[k:])
        if l < 6 or r < 6:
            continue
        sc = score(st[k - 1][2])
        if sc <= 0:
            continue
        val = sc * 10 - abs(l - r) * 0.35 - (8 if max(l, r) > HARD else 0)
        if best is None or val > best[0]:
            best = (val, k)
    if best is None:
        if clen(st) <= HARD:
            return [st]
        ks = [k for k in range(1, len(st)) if bare(st[k - 1][2]) not in NEVER and not bare(st[k - 1][2]).endswith(ATTR_END)
              and clen(st[:k]) >= 6 and clen(st[k:]) >= 6]
        if not ks:
            return [st]
        k = min(ks, key=lambda k: abs(clen(st[:k]) - clen(st[k:])))
    else:
        k = best[1]
    return split_long(st[:k]) + split_long(st[k:])


def make_cues(W, replace=None):
    """W: [(시작, 끝, 단어)] 타임라인 시각 → [(시작, 끝, 자막)]"""
    W = [[a, b, w.strip()] for a, b, w in W if w.strip() and w.strip().rstrip('.,?!') not in FILLER]
    sents, cur = [], []
    for w in W:
        if cur and (is_end(cur[-1][2]) or w[0] - cur[-1][1] > 2.0):
            sents.append(cur)
            cur = []
        cur.append(w)
    if cur:
        sents.append(cur)
    cues = [c for st in sents for c in ([st] if clen(st) <= ONE_LINE else split_long(st))]   # 한 문장이면 30자를 조금 넘어도 한 줄
    merged = []
    for c in cues:            # 아주 짧은 조각(5자 이하)은 앞과 합침
        if merged and clen(c) <= 5 and c[0][0] - merged[-1][-1][1] < 0.5 and clen(merged[-1]) + clen(c) + 1 <= HARD:
            merged[-1] = merged[-1] + c
        else:
            merged.append(c)
    out = []
    for c in merged:
        txt = ' '.join(x[2] for x in c).strip()
        txt = re.sub(r'\s+([,.?!%])', r'\1', txt).rstrip('.,')
        for a, b in (replace or {}).items():
            txt = txt.replace(a, b)
        if not txt or C.is_hallucination(txt, exact_too=False):
            continue
        out.append([c[0][0] + LEAD, c[-1][1] + TAIL, txt])
    for i in range(len(out)):
        if i + 1 < len(out):
            nxt = out[i + 1][0]
            if nxt - out[i][1] < 0.35:
                out[i][1] = nxt - 0.03
            out[i][1] = min(out[i][1], nxt - 0.03)
        if out[i][1] - out[i][0] < 0.8:
            out[i][1] = out[i][0] + 0.8 if i + 1 >= len(out) else max(out[i][1], min(out[i][0] + 0.8, out[i + 1][0] - 0.03))
    return [c for c in out if c[1] - c[0] > 0.1]


# ── 대본 표기로 맞추기 ─────────────────────────────────
def clean_script(raw):
    """대본에서 읽지 않는 것(# 제목, *[화면 신호]*, [대괄호], 목록 기호, 굵게 표시)을 뺀다."""
    out = []
    for line in raw.splitlines():
        s = line.strip()
        if not s or s.startswith(('#', '>', '|', '```', '---')):
            continue
        s = re.sub(r'\*?\[[^\]]*\]\*?', ' ', s)
        s = re.sub(r'^[-*+]\s+|^\d+[.)]\s+', '', s)
        s = s.replace('**', '').replace('__', '')
        if s.strip():
            out.append(s.strip())
    return ' '.join(out)


def _key(ch):
    return ch.isalnum()


def apply_script(TW, script_text):
    """받아쓰기 단어(TW)의 글자를 대본 표기로 바꾼다. 대본에 없는 말(즉흥 멘트)은 받아쓰기 그대로 둔다.
    돌려주는 것: (바뀐 단어 목록, 대본과 일치한 글자 비율)"""
    S = clean_script(script_text)
    merged = []                            # 글자 없는 조각("%", ",")은 앞 단어에 붙인다
    for w in TW:
        if merged and not any(_key(ch) for ch in w[2]):
            p = merged[-1]
            merged[-1] = (p[0], max(p[1], w[1]), p[2].rstrip() + w[2].strip())
        else:
            merged.append(tuple(w))
    TW = merged
    s_norm, s_pos = [], []
    for i, ch in enumerate(S):
        if _key(ch):
            s_norm.append(ch.lower())
            s_pos.append(i)
    a_norm, a_word = [], []
    for k, w in enumerate(TW):
        for ch in w[2]:
            if _key(ch):
                a_norm.append(ch.lower())
                a_word.append(k)
    if not s_norm or not a_norm:
        return TW, 0.0
    A, B = ''.join(a_norm), ''.join(s_norm)
    blocks = difflib.SequenceMatcher(None, A, B, autojunk=False).get_matching_blocks()
    amap = [None] * (len(A) + 1)          # 받아쓰기 글자 위치 → 대본 글자 위치(경계)
    keep_asr = [False] * len(A)           # 대본에 없는 즉흥 멘트 구간
    matched = 0
    pa = pb = 0
    for bl in blocks:
        ga, gb = bl.a - pa, bl.b - pb     # 맞지 않은 구간(받아쓰기 ga글자 ↔ 대본 gb글자)
        if ga:
            bad = (gb == 0 and ga > 6) or (gb and ga > 6 and not (0.4 <= gb / ga <= 2.5))
            for i in range(ga):
                amap[pa + i] = pb + (round(i * gb / ga) if gb else 0)
                keep_asr[pa + i] = bad
        for i in range(bl.size):
            amap[bl.a + i] = bl.b + i
        matched += bl.size
        pa, pb = bl.a + bl.size, bl.b + bl.size
    amap[len(A)] = len(B)
    first = {}                             # 단어마다 첫 글자 위치
    for i, k in enumerate(a_word):
        first.setdefault(k, i)
    starts = sorted(first.items())
    out = []
    last_o1 = None                         # 앞 단어가 대본에서 끝난 자리
    for n, (k, i0) in enumerate(starts):
        i1 = starts[n + 1][1] if n + 1 < len(starts) else len(A)
        w = TW[k]
        if any(keep_asr[i0:i1]):
            out.append((w[0], w[1], w[2]))
            last_o1 = None
            continue
        b0, b1 = amap[i0], amap[i1]
        if b1 <= b0:
            continue                       # 대본에 없는 군말("어", "음")은 빠진다
        o0 = s_pos[b0]
        o1 = s_pos[b1] if b1 < len(s_pos) else len(S)
        seg = S[o0:o1]
        if not seg.strip():
            continue
        if out and last_o1 == o0 and o0 > 0 and not S[o0 - 1].isspace():
            p = out[-1]                    # 대본에서 한 낱말 안이면("구현했고") 띄어 쓰지 않고 앞 단어에 붙인다
            out[-1] = (p[0], w[1], p[2] + seg.rstrip())
        else:
            out.append((w[0], w[1], seg.strip()))
        last_o1 = o1
    return out, matched / max(1, len(A))


def find_word(TW, query, near=None, nth=1):
    """편집본 단어 목록에서 query(띄어쓰기·기호 무시)를 찾아 시작 시각을 돌려준다."""
    q = ''.join(ch.lower() for ch in query if _key(ch))
    if not q:
        return None
    chars, owner = [], []
    for k, w in enumerate(TW):
        for ch in w[2]:
            if _key(ch):
                chars.append(ch.lower())
                owner.append(k)
    s = ''.join(chars)
    hits, i = [], s.find(q)
    while i >= 0:
        hits.append(TW[owner[i]][0])
        i = s.find(q, i + 1)
    if not hits:
        return None
    if near is not None:
        hits = sorted(hits, key=lambda t: abs(t - near))
        return hits[0]
    return hits[nth - 1] if 0 < nth <= len(hits) else None


def srt_time(t):
    t = max(0.0, t)
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f'{h:02d}:{m:02d}:{s:02d},{ms:03d}'


# ── 템플릿 ─────────────────────────────────────────────
class Template:
    def __init__(self, folder):
        self.folder = Path(folder)
        self.D = C.read_draft(self.folder / 'draft_content.json')
        self.M = C.material_index(self.D)
        segs = [(t, s) for t in self.D['tracks'] for s in t['segments']]

        def kind(s):
            return self.M.get(s['material_id'], (None, {}))[1].get('type')

        def pack(s):
            if s is None:
                return None
            refs = {r: copy.deepcopy(self.M[r]) for r in s.get('extra_material_refs', []) if r in self.M}
            return copy.deepcopy(s), copy.deepcopy(self.M[s['material_id']][1]), refs

        v = [s for t, s in segs if t['type'] == 'video' and kind(s) == 'video']
        self.vid = pack(next((s for s in v if not s.get('common_keyframes')), v[0] if v else None))
        a = [s for t, s in segs if t['type'] == 'audio' and kind(s) == 'extract_music']
        self.aud_converted = False
        if not a:      # 로컬 파일 오디오가 없으면 라이브러리 소리를 로컬 형식으로 바꿔 쓴다(경고)
            a = [s for t, s in segs if t['type'] == 'audio']
            self.aud_converted = bool(a)
        self.aud = pack(a[0] if a else None)
        texts = [t for t in self.D['tracks'] if t['type'] == 'text' and t['segments']]
        self.text_track = copy.deepcopy(max(texts, key=lambda t: len(t['segments']))) if texts else None
        self.txt = pack(self.text_track['segments'][0]) if texts else None


class Builder:
    def __init__(self, tpl):
        self.tpl = tpl
        D = copy.deepcopy(tpl.D)
        for k, v in D['materials'].items():
            if isinstance(v, list):
                D['materials'][k] = []
        D['tracks'] = []
        self.D = D
        self.M = D['materials']
        self.mats = {}       # (경로, 종류) → 재료
        self.tracks = {}
        self.sub_group = f'import_{int(time.time() * 1000)}'

    def track(self, name, typ, proto=None):
        if name not in self.tracks:
            t = dict(id=uid(), type=typ, segments=[], flag=0, attribute=0, name=name, is_default_name=False)
            if proto:
                t.update(flag=proto.get('flag', 0), attribute=proto.get('attribute', 0))
            self.tracks[name] = t
            self.D['tracks'].append(t)
        return self.tracks[name]

    def free_track(self, base, typ, start_us, dur_us, proto=None):
        """base, base 2, base 3 … 중 이 구간이 비어 있는 트랙 이름(한 트랙 안 클립은 겹치면 안 된다)."""
        n = 1
        while True:
            name = base if n == 1 else f'{base} {n}'
            t = self.tracks.get(name)
            if t is None or all(s['target_timerange']['start'] + s['target_timerange']['duration'] <= start_us
                                or start_us + dur_us <= s['target_timerange']['start'] for s in t['segments']):
                self.track(name, typ, proto)
                return name
            n += 1

    def clone_refs(self, refs, kind, dur_us=0):
        out = []
        for r, (k, m) in refs.items():
            if k == 'audio_fades':
                continue
            v = copy.deepcopy(m)
            v['id'] = uid()
            if k == 'speeds':
                v.update(speed=1.0, curve_speed=None)
            if k == 'material_animations':
                if kind != 'text':
                    v['animations'] = []
                else:
                    for an in v.get('animations', []):
                        if an.get('type') == 'out':
                            an['start'] = max(0, dur_us - an.get('duration', 0))
            self.M.setdefault(k, []).append(v)
            out.append(v['id'])
        return out

    def material(self, path, typ):
        path = Path(path).resolve()
        key = (path.as_posix(), typ)
        if key in self.mats:
            return self.mats[key]
        info = C.media_info(path)
        if typ == 'audio':
            if not self.tpl.aud:
                C.die('템플릿 프로젝트에 오디오 클립이 없습니다. 로컬 음성 파일(효과음·녹음 등)을 하나라도 올려 둔 프로젝트를 템플릿으로 고르세요.')
            m = copy.deepcopy(self.tpl.aud[1])
            m.update(id=uid(), path=path.as_posix(), name=path.name, duration=C.us(info['duration']), type='extract_music',
                     unique_id=uuid.uuid4().hex, local_material_id='', category_name='local', wave_points=[])
            for k in ('effect_id', 'category_id', 'music_id', 'request_id', 'resource_id', 'third_resource_id', 'source_from',
                      'music_source', 'pgc_id', 'pgc_name', 'query', 'search_id'):
                if k in m:
                    m[k] = ''
            self.M.setdefault('audios', []).append(m)
        else:
            if not self.tpl.vid:
                C.die('템플릿 프로젝트에 영상 클립이 없습니다. 영상 파일을 하나라도 올려 둔 프로젝트를 템플릿으로 고르세요.')
            m = copy.deepcopy(self.tpl.vid[1])
            m.update(id=uid(), unique_id=uuid.uuid4().hex, path=path.as_posix(), material_name=path.name, type='video',
                     width=info['width'], height=info['height'], duration=C.us(info['duration']), has_audio=info['has_audio'],
                     local_material_id='', local_id='', media_path='', reverse_path='', intensifies_path='',
                     reverse_intensifies_path='', intensifies_audio_path='', cartoon_path='', freeze=None, smart_motion=None)
            m['crop'] = dict(upper_left_x=0.0, upper_left_y=0.0, upper_right_x=1.0, upper_right_y=0.0,
                             lower_left_x=0.0, lower_left_y=1.0, lower_right_x=1.0, lower_right_y=1.0)
            if isinstance(m.get('video_algorithm'), dict):
                m['video_algorithm']['algorithms'] = []
                m['video_algorithm']['path'] = ''
            if isinstance(m.get('matting'), dict):
                m['matting'].update(flag=0, path='', strokes=[], interactiveTime=[])
            self.M.setdefault('videos', []).append(m)
        self.mats[key] = (m, info)
        return self.mats[key]

    def put_video(self, track, path, start_us, dur_us, src_us, scale, volume):
        m, info = self.material(path, 'video')
        s = copy.deepcopy(self.tpl.vid[0])
        s.update(id=uid(), material_id=m['id'], extra_material_refs=self.clone_refs(self.tpl.vid[2], 'video'),
                 common_keyframes=[], keyframe_refs=[], volume=volume, last_nonzero_volume=1.0, speed=1.0, visible=True,
                 group_id='', raw_segment_id='', desc=Path(path).name, reverse=False, is_loop=False,
                 target_timerange=dict(start=start_us, duration=dur_us),
                 source_timerange=dict(start=src_us, duration=dur_us),
                 render_timerange=dict(start=0, duration=0))
        s['clip'] = dict(scale=dict(x=scale, y=scale), rotation=0.0, transform=dict(x=0.0, y=0.0),
                         flip=dict(vertical=False, horizontal=False), alpha=1.0)
        s['uniform_scale'] = dict(on=True, value=scale)
        self.track(track, 'video')['segments'].append(s)
        return s

    def put_audio(self, track, path, start_us, dur_us, src_us, volume=1.0):
        m, info = self.material(path, 'audio')
        s = copy.deepcopy(self.tpl.aud[0])
        s.update(id=uid(), material_id=m['id'], extra_material_refs=self.clone_refs(self.tpl.aud[2], 'audio'),
                 common_keyframes=[], keyframe_refs=[], volume=volume, last_nonzero_volume=1.0, speed=1.0, visible=True,
                 group_id='', raw_segment_id='', desc=Path(path).name, reverse=False, is_loop=False,
                 target_timerange=dict(start=start_us, duration=dur_us),
                 source_timerange=dict(start=src_us, duration=dur_us),
                 render_timerange=dict(start=0, duration=0))
        self.track(track, 'audio')['segments'].append(s)
        return s

    def put_text(self, track, text, start_us, dur_us, emphasis=None):
        """emphasis=(x, y, 크기 배수)면 자막이 아닌 강조 글자(type text)로, 그 위치에 넣는다."""
        seg_t, mat_t, refs = self.tpl.txt
        m = copy.deepcopy(mat_t)
        m['id'] = uid()
        c = json.loads(m['content'])
        n = len(text.encode('utf-16-le')) // 2          # CapCut 범위는 UTF-16 글자 수
        st = copy.deepcopy((c.get('styles') or [{}])[0])
        st['range'] = [0, n]
        if emphasis and isinstance(st.get('size'), (int, float)):
            st['size'] = round(st['size'] * emphasis[2], 2)
        c['text'] = text
        c['styles'] = [st]
        m['content'] = json.dumps(c, ensure_ascii=False)
        for k in ('words', 'current_words'):
            if isinstance(m.get(k), dict):
                m[k] = {kk: [] for kk in m[k]}
        for k in ('base_content', 'recognize_text', 'recognize_task_id'):
            if k in m:
                m[k] = ''
        for k in ('text_to_audio_ids', 'relevance_segment'):
            if k in m:
                m[k] = []
        if emphasis:
            m['type'] = 'text'
        m['group_id'] = self.sub_group if m.get('type') == 'subtitle' else ''
        self.M.setdefault('texts', []).append(m)
        s = copy.deepcopy(seg_t)
        s.update(id=uid(), material_id=m['id'], extra_material_refs=self.clone_refs(refs, 'text', dur_us),
                 common_keyframes=[], keyframe_refs=[], visible=True, group_id='', raw_segment_id='', desc=text[:20],
                 target_timerange=dict(start=start_us, duration=dur_us), render_timerange=dict(start=0, duration=0))
        if emphasis:
            s.setdefault('clip', {})['transform'] = dict(x=round((emphasis[0] - 0.5) * 2, 4), y=round((0.5 - emphasis[1]) * 2, 4))
        self.track(track, 'text', None if emphasis else self.tpl.text_track)['segments'].append(s)
        return s


def canvas_for(info, cur):
    """원본 방향에 맞는 캔버스. 템플릿과 방향이 같으면 템플릿 캔버스를 그대로 쓴다."""
    w, h = info['width'], info['height']
    if not w or not h:
        return cur
    kind = 'land' if w >= h * 1.2 else 'port' if h >= w * 1.2 else 'sq'
    cw, ch = cur.get('width', 1920), cur.get('height', 1080)
    ckind = 'land' if cw >= ch * 1.2 else 'port' if ch >= cw * 1.2 else 'sq'
    if kind == ckind:
        return cur
    new = dict(cur)
    new.update({'land': dict(width=1920, height=1080, ratio='16:9'), 'port': dict(width=1080, height=1920, ratio='9:16'),
                'sq': dict(width=1080, height=1080, ratio='1:1')}[kind])
    return new


def cover_scale(info, cv):
    """CapCut 기본(화면 안에 맞춤) 대비 배율: 검은 띠 없이 화면을 채운다."""
    w, h = info['width'], info['height']
    if not w or not h:
        return 1.0
    f = min(cv['width'] / w, cv['height'] / h)
    return round(max(cv['width'] / (w * f), cv['height'] / (h * f)), 4)


def load_words(p):
    j = C.read_json(p)
    out = []
    for w in j:
        if isinstance(w, dict):
            out.append((float(w['start']), float(w['end']), str(w.get('word', ''))))
        else:
            out.append((float(w[0]), float(w[1]), str(w[2])))
    return out


def write_staging(b, tpl, stage, name, dest, media_paths, cover_src):
    D = b.D
    if stage.exists():
        if not (stage / MARKER).exists():
            C.die(f'스테이징 폴더가 이미 있는데 이 스크립트가 만든 것이 아닙니다. 지우지 않습니다: {stage}')
        shutil.rmtree(stage)
    ign = shutil.ignore_patterns('*.bak', '.locked', 'Resources', 'adjust_mask', 'smart_crop', 'subdraft', 'draft_cover.jpg',
                                 MARKER)
    shutil.copytree(tpl.folder, stage, ignore=ign)
    for sub in ('adjust_mask', 'matting', 'qr_upload', 'smart_crop', 'subdraft', 'Resources/audioAlg', 'Resources/videoAlg',
                'Resources/combination'):
        (stage / sub).mkdir(parents=True, exist_ok=True)
    tl = stage / 'Timelines'
    tl.mkdir(exist_ok=True)
    pj_path = tl / 'project.json'
    pj = C.read_json(pj_path) if pj_path.exists() else {}
    old_main = pj.get('main_timeline_id') or tpl.D['id']
    new = D['id']
    tl_name = next((x.get('name') for x in pj.get('timelines', []) if x.get('id') == old_main), None) or 'Timeline 01'
    for x in list(tl.iterdir()):          # 메인 타임라인 하나만 남긴다
        if x.is_dir() and x.name != old_main:
            shutil.rmtree(x)
    if (tl / old_main).exists():
        (tl / old_main).rename(tl / new)
    (tl / new).mkdir(exist_ok=True)
    js = json.dumps(D, ensure_ascii=False, separators=(',', ':'))
    for p in [stage / 'draft_content.json', stage / 'template-2.tmp', tl / new / 'draft_content.json']:
        p.write_text(js, 'utf-8')
    for p in [tl / new / 'template-2.tmp', tl / new / 'template.tmp', stage / 'template.tmp']:
        if p.exists():
            p.write_text(js, 'utf-8')
    now = int(time.time())
    pj.update(id=new, main_timeline_id=new, create_time=now * C.US, update_time=now * C.US,
              timelines=[dict(create_time=now * C.US, id=new, is_marked_delete=False, name=tl_name, update_time=now * C.US)])
    C.write_json(pj_path, pj, compact=True)
    C.write_json(stage / 'timeline_layout.json', {'dockItems': [{'dockIndex': 0, 'ratio': 1, 'timelineIds': [new],
                                                                 'timelineNames': [tl_name]}], 'layoutOrientation': 1}, compact=True)
    # 재료 목록(meta)
    mp = stage / 'draft_meta_info.json'
    meta = C.read_json(mp) if mp.exists() else {}
    items = []
    proto = None
    for g in meta.get('draft_materials', []):
        if g.get('type') == 0 and g.get('value'):
            proto = g['value'][0]
    for (path, typ), (m, info) in b.mats.items():
        it = copy.deepcopy(proto) if proto else dict(ai_group_type='', enter_from=0, item_source=1, material_color_tag='', md5='',
                                                     sub_time_range={'duration': -1, 'start': -1}, type=0)
        dur = m.get('duration', 0)
        it.update(id=m['id'], file_Path=path, extra_info=Path(path).name, metetype='music' if typ == 'audio' else 'video',
                  width=info.get('width', 0), height=info.get('height', 0), duration=dur, create_time=now, import_time=now,
                  import_time_ms=now * C.US, roughcut_time_range={'duration': dur, 'start': 0})
        items.append(it)
    for g in meta.get('draft_materials', []):
        g['value'] = items if g.get('type') == 0 else []
    size = 0
    for p in media_paths:
        try:
            size += Path(p).stat().st_size
        except OSError:
            pass
    meta.update(draft_id=new, draft_name=name, draft_fold_path=dest.as_posix(), draft_root_path=dest.parent.as_posix(),
                draft_cover='draft_cover.jpg', tm_draft_create=now * C.US, tm_draft_modified=now * C.US,
                tm_duration=D['duration'], draft_timeline_materials_size_=size, draft_is_invisible=False)
    C.write_json(mp, meta, compact=True)
    vp = stage / 'draft_virtual_store.json'
    if vp.exists():
        vs = C.read_json(vp)
        for g in vs.get('draft_virtual_store', []):
            if g.get('type') == 1:
                g['value'] = [{'child_id': it['id'], 'parent_id': ''} for it in items]
            elif g.get('type') != 0:
                g['value'] = []
        C.write_json(vp, vs, compact=True)
    (stage / 'draft_settings').write_text(f'[General]\ncloud_last_modify_platform=windows\ndraft_create_time={now}\n'
                                          f'draft_last_edit_time={now}\nreal_edit_seconds=0\nreal_edit_keys=0\n', 'utf-8')
    if cover_src:
        try:
            C.run(['ffmpeg', '-v', 'error', '-y', '-ss', f'{cover_src[1]:.3f}', '-i', cover_src[0], '-frames:v', '1',
                   '-vf', 'scale=720:-2', stage / 'draft_cover.jpg'])
        except Exception as e:
            print('[주의] 표지 이미지 만들기 실패(무시해도 됨):', str(e)[:120])
    (stage / MARKER).write_text('capcut_build.py 가 만든 스테이징 폴더입니다. CapCut 설치 때 이 파일은 복사되지 않습니다.\n', 'utf-8')


def install(stage, cc, name, backup_root):
    """새 폴더를 검증한 뒤 목록에 등록하고, 실패 시 소유한 변경만 되돌린다."""
    if C.capcut_running():
        print('[거부] CapCut이 켜져 있습니다. CapCut을 완전히 끈 뒤 다시 --install 해 주세요(스테이징은 그대로 있음).')
        return 2
    cc = Path(cc).resolve()
    stage = Path(stage).resolve()
    if not name or name in ('.', '..') or '/' in name or '\\' in name:
        print('[거부] 새 프로젝트 이름은 한 단계의 폴더 이름이어야 합니다.')
        return 3
    dest = cc / name
    catalog = cc / 'root_meta_info.json'
    if not catalog.exists():
        print(f'[거부] 프로젝트 목록 파일이 없습니다: {catalog}. CapCut에서 프로젝트를 하나 만든 뒤 다시 해 주세요.')
        return 3
    raw = catalog.read_bytes()
    before = hashlib.sha256(raw).hexdigest()
    try:
        cat = json.loads(raw.decode('utf-8-sig'))
    except Exception:
        print('[거부] root_meta_info.json 을 읽을 수 없습니다(이 CapCut 버전은 지원하지 않음).')
        return 3
    store = cat.get('all_draft_store')
    if not isinstance(store, list) or not store:
        print('[거부] root_meta_info.json 형식이 예상과 다릅니다.')
        return 3
    if dest.exists() or any(isinstance(x, dict) and x.get('draft_name') == name for x in store):
        print(f'[거부] 같은 이름의 프로젝트가 이미 있습니다: {name}. 덮어쓰지 않습니다. 새 이름(예: _v002)으로 다시 만드세요.')
        return 3
    try:
        meta = C.read_json(stage / 'draft_meta_info.json')
        draft = C.read_draft(stage / 'draft_content.json')
        if meta['draft_id'] != draft['id'] or meta['draft_name'] != name:
            raise ValueError('스테이징 프로젝트 ID 또는 이름이 일치하지 않습니다.')
        draft_hash = C.sha256(stage / 'draft_content.json')
    except (OSError, KeyError, ValueError, TypeError) as e:
        print(f'[거부] 스테이징 프로젝트가 올바르지 않습니다: {e}')
        return 3
    token = uuid.uuid4().hex
    backup = Path(backup_root) / f'{time.strftime("%Y%m%d_%H%M%S")}_{token[:8]}'
    try:
        backup.mkdir(parents=True, exist_ok=False)
        (backup / 'root_meta_info.json').write_bytes(raw)
    except OSError as e:
        print(f'[거부] 프로젝트 목록 백업 실패. 등록하지 않았습니다: {e}')
        return 3
    entry = copy.deepcopy(store[0])
    entry.update(draft_id=meta['draft_id'], draft_name=name, draft_fold_path=dest.as_posix(), draft_root_path=cc.as_posix(),
                 draft_cover=dest.as_posix() + '/draft_cover.jpg', draft_json_file=dest.as_posix() + '/draft_content.json',
                 tm_draft_create=meta.get('tm_draft_create', C.now_us()), tm_draft_modified=C.now_us(),
                 tm_duration=meta.get('tm_duration', 0), draft_timeline_materials_size=meta.get('draft_timeline_materials_size_', 0),
                 draft_is_invisible=False, draft_cloud_last_action_download=False)
    old = copy.deepcopy(store)
    cat['all_draft_store'] = [entry] + old
    new_raw = json.dumps(cat, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    new_hash = hashlib.sha256(new_raw).hexdigest()
    tmp_dir = cc / f'.{name}.install-{token}.tmp'
    tmp_catalog = cc / f'.root_meta_info.install-{token}.tmp'
    owner_file = f'.capcut_install_owner_{token}'
    promoted = committed = False
    status = 5
    try:
        shutil.copytree(stage, tmp_dir, ignore=shutil.ignore_patterns(MARKER))
        (tmp_dir / owner_file).write_text(token, 'utf-8')
        if C.sha256(tmp_dir / 'draft_content.json') != draft_hash or C.sha256(stage / 'draft_content.json') != draft_hash:
            raise RuntimeError('복사한 프로젝트와 스테이징 파일이 다릅니다.')
        if C.capcut_running() or C.sha256(catalog) != before:
            status = 4
            raise RuntimeError('복사하는 동안 CapCut이 켜졌거나 프로젝트 목록이 바뀌었습니다.')
        tmp_dir.rename(dest)
        promoted = True
        if C.capcut_running() or C.sha256(catalog) != before:
            status = 4
            raise RuntimeError('목록 등록 직전에 CapCut이 켜졌거나 프로젝트 목록이 바뀌었습니다.')
        with tmp_catalog.open('xb') as f:
            f.write(new_raw)
        os.replace(tmp_catalog, catalog)
        committed = True
        after = C.read_json(catalog)
        if (after.get('all_draft_store', [])[:1] != [entry]
                or after['all_draft_store'][1:] != old
                or C.sha256(dest / 'draft_content.json') != draft_hash):
            raise RuntimeError('등록 후 프로젝트 목록 또는 프로젝트 파일 검증에 실패했습니다.')
        (dest / owner_file).unlink()
        print(f'설치 완료: {dest}')
        print(f'  목록 백업: {backup / "root_meta_info.json"}')
        return 0
    except Exception as e:
        print(f'[중단] CapCut 등록 실패: {e}')
        restored = not committed
        if committed:
            # 다른 프로세스가 목록을 다시 썼다면 백업으로 덮지 않는다.
            try:
                if not C.capcut_running() and C.sha256(catalog) == new_hash:
                    with tmp_catalog.open('xb') as f:
                        f.write(raw)
                    os.replace(tmp_catalog, catalog)
                    restored = C.sha256(catalog) == before
            except Exception as restore_error:
                print(f'[주의] 목록 복구 실패: {restore_error}')
        if tmp_dir.exists() and tmp_dir.parent.resolve() == cc:
            try:
                shutil.rmtree(tmp_dir)
            except OSError as cleanup_error:
                print(f'[주의] 임시 프로젝트 폴더 정리 실패: {cleanup_error}')
        if promoted and restored and not C.capcut_running():
            try:
                if (dest / owner_file).read_text('utf-8') == token and dest.parent.resolve() == cc:
                    shutil.rmtree(dest)
            except OSError as cleanup_error:
                print(f'[주의] 새 프로젝트 폴더 정리 실패: {cleanup_error}')
        if not restored or (promoted and dest.exists()):
            print(f'[주의] 자동 복구가 끝나지 않았습니다. 목록 백업 {backup / "root_meta_info.json"}, 새 폴더 {dest}를 확인해 주세요.')
        else:
            print('프로젝트 목록과 새 폴더를 등록 전 상태로 되돌렸습니다.')
        return status
    finally:
        tmp_catalog.unlink(missing_ok=True)


def place_overlays(b, items, timeline, total, media, main_scale, cv, TW_fix, TW_raw, base_dir):
    """덧입히기 목록을 트랙에 얹는다. 돌려주는 것: 실제로 놓인 자리 목록(_timeline.json 에 남김)."""
    def resolve(p):
        p = Path(p)
        if p.is_absolute():
            return p
        for root in (Path.cwd(), base_dir):
            if (root / p).exists():
                return (root / p).resolve()
        return (Path.cwd() / p).resolve()

    def src_to_edit(x):
        for r in timeline:
            if r['src_in'] <= x < r['src_out']:
                return r['start'] + (x - r['src_in'])
        nxt = [r for r in timeline if r['src_in'] >= x]
        return nxt[0]['start'] if nxt else total

    def anchor(o, k_at, k_src, k_word):
        if o.get(k_at) is not None:
            return float(o[k_at])
        if o.get(k_src) is not None:
            return src_to_edit(float(o[k_src]))
        if o.get(k_word):
            for W in (TW_fix, TW_raw):
                t = find_word(W, o[k_word], o.get('near'), int(o.get('nth', 1)))
                if t is not None:
                    return t
            return 'missing'
        return None

    prio = {'zoom': 0, 'motion': 1, 'text': 2, 'sfx': 3, 'bgm': 4}
    order = sorted(range(len(items)), key=lambda i: (prio.get(items[i].get('type'), 9), i))
    placed, miss = [], []
    for i in order:
        o = items[i]
        typ = o.get('type')
        st = anchor(o, 'at', 'src', 'word')
        if st == 'missing' or st is None:
            miss.append(f'{i + 1}번 {typ}: ' + (f'낱말 "{o.get("word")}"을 편집본에서 못 찾음' if st == 'missing' else '시작 시각(at/src/word) 없음'))
            continue
        st = max(0.0, st + float(o.get('offset', 0.0)))
        en = anchor(o, 'end', 'end_src', 'end_word')
        if en == 'missing':
            en = None
        dur = float(o['dur']) if o.get('dur') is not None else (en - st if en is not None else None)
        rec = dict(n=i + 1, type=typ, start=round(st, 3), note=o.get('note', ''))
        if st >= total:
            miss.append(f'{i + 1}번 {typ}: 시작 {st:.2f}초가 편집본 길이({total:.2f}초) 밖')
            continue

        if typ == 'sfx':
            f = resolve(o['file'])
            if not f.exists():
                miss.append(f'{i + 1}번 sfx: 파일 없음 {f}')
                continue
            fi = C.media_info(f)
            src0 = float(o.get('from', 0.0))
            du = min(dur or (fi['duration'] - src0), fi['duration'] - src0, total - st)
            if du <= 0.02:
                miss.append(f'{i + 1}번 sfx: 길이 0')
                continue
            db = float(o.get('db', -20))
            name = b.free_track('효과음', 'audio', C.us(st), C.us(du))
            b.put_audio(name, f, C.us(st), C.us(du), C.us(src0), round(10 ** (db / 20), 4))
            rec.update(track=name, dur=round(du, 3), file=f.as_posix(), db=db)

        elif typ == 'bgm':
            f = resolve(o['file'])
            if not f.exists():
                miss.append(f'{i + 1}번 bgm: 파일 없음 {f}')
                continue
            fi = C.media_info(f)
            end = min(total, st + dur) if dur else total
            db = float(o.get('db', -40))
            name = b.free_track('BGM', 'audio', C.us(st), C.us(end - st))
            t, k = st, 0
            while end - t > 0.05:
                du = min(fi['duration'], end - t)
                b.put_audio(name, f, C.us(t), C.us(du), 0, round(10 ** (db / 20), 4))
                t += du
                k += 1
            rec.update(track=name, dur=round(end - st, 3), file=f.as_posix(), db=db, clips=k)

        elif typ == 'motion':
            f = resolve(o['file'])
            if not f.exists():
                miss.append(f'{i + 1}번 motion: 파일 없음 {f}')
                continue
            fi = C.media_info(f)
            du = min(dur or fi['duration'], fi['duration'], total - st)
            name = b.free_track('모션', 'video', C.us(st), C.us(du))
            sc = cover_scale(fi, cv) * float(o.get('scale', 1.0))
            s = b.put_video(name, f, C.us(st), C.us(du), 0, sc, 1.0 if o.get('sound') else 0.0)
            fade = min(float(o.get('fade', 0.2)), du / 3)
            if fade > 0:
                d = C.us(du)
                s['common_keyframes'] = [kf('KFTypeAlpha', [(0, 0.0), (C.us(fade), 1.0), (d - C.us(fade), 1.0), (d, 0.0)])]
            rec.update(track=name, dur=round(du, 3), file=f.as_posix())

        elif typ == 'text':
            du = min(dur or 1.5, total - st)
            name = b.free_track('강조 글자', 'text', C.us(st), C.us(du))
            b.put_text(name, str(o['text']), C.us(st), C.us(du),
                       emphasis=(float(o.get('x', 0.5)), float(o.get('y', 0.5)), float(o.get('size', 1.6))))
            rec.update(track=name, dur=round(du, 3), text=o['text'])

        elif typ == 'zoom':
            du = min(dur or 2.5, total - st)
            en = st + du
            z = float(o.get('scale', 1.3))
            ramp = max(0.0, min(float(o.get('ramp', 0.3)), du / (2 if o.get('out', 'smooth') == 'smooth' else 1)))
            px, py = (float(o.get('x', 0.5)) - 0.5) * 2, (0.5 - float(o.get('y', 0.5))) * 2

            def clamp(v):
                return max(-(z - 1), min(z - 1, v))
            tx, ty = clamp(-z * px), clamp(-z * py)     # 가리킨 곳을 가운데 쪽으로, 화면 밖 검은 띠는 생기지 않게
            pts = [(st, 1.0, 0.0, 0.0), (st + ramp, z, tx, ty)]
            pts += [(en - ramp, z, tx, ty), (en, 1.0, 0.0, 0.0)] if o.get('out', 'smooth') == 'smooth' else [(en, z, tx, ty)]

            def at(t):
                for (t0, *v0), (t1, *v1) in zip(pts, pts[1:]):
                    if t0 <= t <= t1:
                        f = 0.0 if t1 <= t0 else (t - t0) / (t1 - t0)
                        return [a_ + (b_ - a_) * f for a_, b_ in zip(v0, v1)]
                return pts[-1][1:] if t > pts[-1][0] else pts[0][1:]
            pieces = []
            for r in timeline:            # 줌 구간이 문장 클립 여러 개에 걸치면 클립마다 조각으로 얹는다
                p0, p1 = max(st, r['start']), min(en, r['start'] + r['dur'])
                if p1 - p0 < 0.04:
                    continue
                src0 = r['src_in'] + (p0 - r['start'])
                times = [p0] + [t for t, *_ in pts if p0 < t < p1] + [p1]
                name = b.free_track('줌', 'video', C.us(p0), C.us(p1) - C.us(p0))
                s = b.put_video(name, media, C.us(p0), C.us(p1) - C.us(p0), C.us(src0), main_scale * at(p0)[0], 0.0)
                off = C.us(src0)
                vals = [(off + C.us(t - p0), at(t)) for t in times]
                s['common_keyframes'] = [kf('KFTypeScaleX', [(t, main_scale * v[0]) for t, v in vals]),
                                         kf('KFTypeScaleY', [(t, main_scale * v[0]) for t, v in vals]),
                                         kf('KFTypePositionX', [(t, v[1]) for t, v in vals]),
                                         kf('KFTypePositionY', [(t, v[2]) for t, v in vals])]
                pieces.append(name)
            rec.update(track=pieces[0] if pieces else '', dur=round(du, 3), scale=z, pieces=len(pieces))
        else:
            miss.append(f'{i + 1}번: 모르는 종류 "{typ}" (sfx, zoom, motion, text, bgm 중 하나)')
            continue
        placed.append(rec)

    placed.sort(key=lambda r: r['start'])
    cnt = {}
    for r in placed:
        cnt[r['type']] = cnt.get(r['type'], 0) + 1
    print(f'덧입히기 {len(placed)}개: ' + ', '.join(f'{k} {v}' for k, v in cnt.items()))
    for m in miss:
        print('  [못 넣음]', m)
    # 규칙 점검: 효과음은 본편 1분에 보통 1~2개, 많아도 5개(rules.md 6장)
    sfx = [r['start'] for r in placed if r['type'] == 'sfx']
    if sfx and total >= 30:
        rate = len(sfx) / (total / 60)
        busiest = max(sum(1 for y in sfx if x <= y < x + 60) for x in sfx)
        if busiest > 5 or (total >= 120 and rate > 3):
            print(f'  [규칙 점검] 효과음이 1분에 평균 {rate:.1f}개, 가장 많은 1분에 {busiest}개입니다. '
                  f'기준(본편 1분에 1~2개, 많아도 5개)보다 많습니다. 줄일지 사용자에게 물어보세요.')
    zooms = [r['start'] for r in placed if r['type'] == 'zoom']
    if len(zooms) >= 2 and min(b_ - a_ for a_, b_ in zip(zooms, zooms[1:])) < 4:
        print('  [규칙 점검] 4초 안에 줌이 두 번 있습니다. 줌은 잦지 않게(rules.md 8장).')
    return placed


def main():
    C.setup_console()
    ap = argparse.ArgumentParser(description='컷 계획 → CapCut 프로젝트 조립')
    ap.add_argument('--template', required=True, help='형식을 복제할 기존 CapCut 프로젝트 이름(또는 프로젝트 폴더 경로)')
    ap.add_argument('--plan', required=True, help='cut_plan.py 가 만든 plan.json')
    ap.add_argument('--media', required=True, help='원본 영상(또는 음성) 파일')
    ap.add_argument('--name', required=True, help='새 프로젝트 이름(기존 이름과 겹치면 안 됨)')
    ap.add_argument('--voice', help='따로 녹음한 마이크 파일(원본과 같은 시각). 주면 영상 소리는 끈다')
    ap.add_argument('--voice-offset', type=float, default=0.0, help='마이크 시각 = 원본 시각 + 이 값(초)')
    ap.add_argument('--media-db', type=float, default=None, help='영상 클립 소리 크기(dB). --voice 를 주면 기본은 끔')
    ap.add_argument('--words', help='words.json(transcribe.py 결과). 없으면 plan.json 옆 또는 plan 안 단어를 쓴다')
    ap.add_argument('--subtitles', action='store_true', help='의미 단위 자막(텍스트 클립 + SRT)을 넣는다')
    ap.add_argument('--replace', help='자막 표기 고치기 JSON 파일 {"틀린 말": "고칠 말", ...}')
    ap.add_argument('--script', help='대본 파일(.md/.txt). 자막 글자를 대본 표기로 맞춘다')
    ap.add_argument('--overlays', help='효과음·줌·모션 카드·강조 글자·배경음 목록 JSON(형식은 맨 위 설명)')
    ap.add_argument('--capcut-dir', help='CapCut 프로젝트 폴더(자동으로 못 찾을 때)')
    ap.add_argument('--staging', help='스테이징 폴더(기본: plan.json 옆 capcut_staging)')
    ap.add_argument('--install', action='store_true', help='CapCut 프로젝트 목록에 등록(CapCut을 끈 상태에서만)')
    a = ap.parse_args()

    C.need_ffmpeg()
    if re.search(r'[\\/:*?"<>|]', a.name) or not a.name.strip():
        C.die('프로젝트 이름에 \\ / : * ? " < > | 는 쓸 수 없습니다.')
    plan_path = Path(a.plan).resolve()
    plan = C.read_json(plan_path)
    segs = plan['segments'] if isinstance(plan, dict) else plan
    segs = [s for s in segs if float(s['src_out']) - float(s['src_in']) > 0.04]
    if not segs:
        C.die('plan.json 에 남길 구간이 없습니다.')
    media = Path(a.media).resolve()
    if not media.exists():
        C.die(f'원본이 없습니다: {media}')
    info = C.media_info(media)
    if info['kind'] == 'photo':
        C.die('--media 는 영상 또는 음성 파일이어야 합니다.')
    if info['has_video'] and max(info['width'], info['height']) > 2200:
        print(f'[주의] 원본이 {info["width"]}x{info["height"]}로 큽니다. 화면 녹화처럼 키프레임 간격이 길면 CapCut 미리보기가 끊길 수 있습니다.\n'
              f'  편집용 사본 예: ffmpeg -i 원본.mp4 -vf scale=1920:-2 -c:v libx264 -crf 18 -g 15 -c:a copy 원본_edit.mp4')
    voice = Path(a.voice).resolve() if a.voice else None
    if voice and not voice.exists():
        C.die(f'--voice 파일이 없습니다: {voice}')

    cc = C.find_capcut_dir(a.capcut_dir, required=a.install or not Path(a.template).exists())
    tpl_dir = C.resolve_project(a.template, a.capcut_dir)
    tpl = Template(tpl_dir)
    if info['has_video'] and not tpl.vid:
        C.die('템플릿 프로젝트에 영상 클립이 없습니다. 영상이 들어 있는 프로젝트를 템플릿으로 고르세요.')
    need_audio = bool(voice) or not info['has_video']
    if need_audio and not tpl.aud:
        C.die('템플릿 프로젝트에 오디오 클립(로컬 음성 파일)이 없습니다. 효과음·음성 파일을 올려 둔 프로젝트를 고르세요.')
    if need_audio and tpl.aud_converted:
        print('[주의] 템플릿에 로컬 파일 오디오가 없어 라이브러리 소리 형식을 로컬 형식으로 바꿔 씁니다(effect_id 비움).')
    if a.subtitles and not tpl.txt:
        C.die('템플릿 프로젝트에 텍스트(자막) 클립이 없습니다. 자막이 들어 있는 프로젝트를 템플릿으로 고르세요.')
    overlays = []
    if a.overlays:
        ov = C.read_json(a.overlays)
        overlays = ov.get('items', []) if isinstance(ov, dict) else ov
        types = {o.get('type') for o in overlays}
        if types & {'sfx', 'bgm'} and not tpl.aud:
            C.die('효과음·배경음을 넣으려면 템플릿 프로젝트에 로컬 음성 파일 클립이 하나 있어야 합니다.')
        if 'text' in types and not tpl.txt:
            C.die('강조 글자를 넣으려면 템플릿 프로젝트에 텍스트 클립이 하나 있어야 합니다.')
        if types & {'zoom'} and not info['has_video']:
            C.die('줌은 영상 원본에만 쓸 수 있습니다.')
    print(f'템플릿: {tpl_dir.name} (읽기만 함)')

    b = Builder(tpl)
    D = b.D
    cv = canvas_for(info, D.get('canvas_config', {})) if info['has_video'] else D.get('canvas_config', {})
    D['canvas_config'] = cv
    scale = cover_scale(info, cv) if info['has_video'] else 1.0
    vol = 1.0 if not voice else 0.0
    if a.media_db is not None:
        vol = round(10 ** (a.media_db / 20), 4)
    vinfo = C.media_info(voice) if voice else None

    # ── 메인 트랙: 문장 클립 ───────────────────────────────
    t = 0.0
    timeline = []
    for i, s in enumerate(segs):
        src_in = max(0.0, float(s['src_in']))
        src_out = min(float(s['src_out']), info['duration'] or float(s['src_out']))
        if src_out - src_in < 0.04:
            continue
        st_us = C.us(t)
        en_us = C.us(t + (src_out - src_in))
        dur_us = en_us - st_us
        if info['has_video']:
            b.put_video('메인', media, st_us, dur_us, C.us(src_in), scale, vol)
            if voice:
                v_in = src_in + a.voice_offset
                if 0 <= v_in and v_in + (src_out - src_in) <= vinfo['duration'] + 0.05:
                    b.put_audio('보이스', voice, st_us, dur_us, C.us(v_in), 1.0)
                else:
                    print(f'[주의] {i + 1}번 클립은 마이크 파일 범위를 벗어나 보이스를 넣지 못했습니다.')
        else:
            b.put_audio('보이스', media, st_us, dur_us, C.us(src_in), 1.0)
        timeline.append(dict(n=len(timeline) + 1, start=round(st_us / C.US, 3), dur=round(dur_us / C.US, 3),
                             src_in=round(src_in, 3), src_out=round(src_out, 3), text=s.get('text', '')))
        t = en_us / C.US
    total = t

    # ── 편집본 단어(자막·덧입히기 박자용) ─────────────────────
    wpath = Path(a.words).resolve() if a.words else None
    if wpath is None:
        for cand in (plan_path.parent / 'words.json', plan_path.parent.parent / '01_asr' / 'words.json'):
            if cand.exists():
                wpath = cand
                break
    allw = load_words(wpath) if wpath else []
    TW = []
    swapped = 0
    for s, row in zip(segs, timeline):
        a0, a1, t0 = row['src_in'], row['src_out'], row['start']
        ws = [w for w in allw if a0 <= (w[0] + w[1]) / 2 < a1]
        pw = [tuple(w) for w in (s.get('words') or [])]
        if pw:
            got = C.norm_text(''.join(w[2] for w in ws))
            want = C.norm_text(s.get('text', ''))
            if not ws or (want and difflib.SequenceMatcher(None, got, want).ratio() < 0.85):
                ws = [w for w in pw if a0 - 0.1 <= (w[0] + w[1]) / 2 < a1 + 0.1]   # 전체 받아쓰기가 이 구간을 놓치면 조각 받아쓰기로
                swapped += 1
        for w0, w1, w in ws:
            TW.append((t0 + max(0.0, w0 - a0), t0 + min(a1 - a0, max(0.05, w1 - a0)), w))
    TW.sort(key=lambda x: x[0])
    TW_fix = TW
    if a.script:
        sp = Path(a.script).resolve()
        if not sp.exists():
            C.die(f'--script 파일이 없습니다: {sp}')
        TW_fix, ratio = apply_script(TW, sp.read_text('utf-8-sig'))
        print(f'대본 맞추기: 받아쓰기 글자의 {ratio:.0%}가 대본과 일치. 대본에 없는 말은 받아쓰기 그대로 둠.')
        if ratio < 0.5:
            print('  [주의] 일치율이 낮습니다. 이 녹화와 다른 대본이거나 즉흥 멘트가 많습니다. 자막을 꼭 훑어보세요.')

    # ── 자막 ────────────────────────────────────────────
    cues = []
    if a.subtitles:
        print(f'자막 단어: {wpath if wpath else "plan.json 안 단어(조각 받아쓰기)"}')
        rep = C.read_json(a.replace) if a.replace else None
        cues = make_cues(TW_fix, rep)
        cues = [c for c in cues if c[0] < total]
        for c in cues:
            c[1] = min(c[1], total)
        for c0, c1, txt in cues:
            b.put_text('자막', txt, C.us(c0), C.us(c1) - C.us(c0))
        if swapped:
            print(f'  {swapped}개 클립은 전체 받아쓰기와 내용이 달라 조각 받아쓰기 단어로 자막을 만들었습니다.')

    # ── 덧입히기: 줌 → 모션 카드 → 강조 글자 → 효과음 → 배경음 (트랙 쌓는 순서) ──
    placed = place_overlays(b, overlays, timeline, total, media, scale, cv, TW_fix, TW,
                            Path(a.overlays).resolve().parent) if overlays else []

    # ── 정리 ────────────────────────────────────────────
    for x in D['tracks']:
        x['segments'].sort(key=lambda s: s['target_timerange']['start'])
    order = {'video': 0, 'text': 1, 'audio': 2}
    D['tracks'].sort(key=lambda x: order.get(x['type'], 9))
    for i, x in enumerate(D['tracks']):
        for s in x['segments']:
            s['track_render_index'] = i
            s['render_index'] = i if x['type'] in ('video', 'text') else 0
    cc_root = cc if cc else Path(tpl_dir).parent
    dest = cc_root / a.name
    now = int(time.time())
    D.update(id=uid(), name=a.name, duration=C.us(total), path=dest.as_posix(), create_time=now, update_time=now,
             static_cover_image_path='', keyframe_graph_list=[], time_marks=None, relationships=[], group_container=None,
             cover=None, retouch_cover=None)
    D['keyframes'] = {k: [] for k in D.get('keyframes', {})} if isinstance(D.get('keyframes'), dict) else D.get('keyframes')
    fai = D.get('function_assistant_info')
    if isinstance(fai, dict):
        for k, v in fai.items():
            if isinstance(v, list):
                fai[k] = []

    stage_root = Path(a.staging).resolve() if a.staging else plan_path.parent / 'capcut_staging'
    stage = stage_root / a.name
    stage_root.mkdir(parents=True, exist_ok=True)
    media_paths = [media] + ([voice] if voice else []) + sorted({p['file'] for p in placed if p.get('file')})
    write_staging(b, tpl, stage, a.name, dest, media_paths, (media, segs[0]['src_in'] + 0.5) if info['has_video'] else None)
    if cues:
        (stage_root / f'{a.name}.srt').write_text('\n'.join(f'{k + 1}\n{srt_time(c0)} --> {srt_time(c1)}\n{txt}\n'
                                                            for k, (c0, c1, txt) in enumerate(cues)), 'utf-8-sig')
    C.write_json(stage_root / f'{a.name}_timeline.json', dict(name=a.name, media=media.as_posix(), total=round(total, 3),
                                                              clips=timeline, subtitles=[[round(x, 3), round(y, 3), z] for x, y, z in cues],
                                                              overlays=placed))
    ntr = {x['name']: len(x['segments']) for x in D['tracks']}
    print(f'조립 완료: {a.name} · 길이 {C.mmss(total)} · 트랙 {ntr} · 캔버스 {cv.get("width")}x{cv.get("height")} · 화면 배율 {scale}')
    print(f'  스테이징: {stage}')
    if cues:
        print(f'  자막 {len(cues)}개 · 최대 {max(len(c[2]) for c in cues)}자 · SRT: {stage_root / (a.name + ".srt")}')
    if a.install:
        if cc is None:
            C.die('CapCut 프로젝트 폴더를 찾지 못해 설치할 수 없습니다(--capcut-dir).')
        sys.exit(install(stage, cc, a.name, stage_root / 'backups'))
    else:
        print('  CapCut 등록은 아직 안 했습니다. CapCut을 끈 뒤 같은 명령에 --install 을 붙이면 등록합니다.')


if __name__ == '__main__':
    main()
