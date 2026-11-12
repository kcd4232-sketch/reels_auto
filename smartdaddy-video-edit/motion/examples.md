# 모션 카드 예시

아래 명령은 값 전달 예시다. 실행할 때 `scripts/render_motion.py`와 `motion/cards.html`은 스킬 폴더의 절대 경로, `편집/` 출력은 영상 작업 폴더의 절대 경로로 바꾼다. 결과는 1920×1080, 30fps이고 마지막 0.5초는 멈춰 있다. 먼저 `--frames 0.5,1.5,3.5`로 PNG 몇 장을 보고, 괜찮으면 mp4로 렌더한다.

## 값 넘기는 법

- `--query "kind=종류&키=값&키=값"`. 한글과 띄어쓰기는 그대로 쓴다. render_motion.py가 주소에 맞게 바꿔 준다.
- 목록은 `|`로 나눈다. 예: `items=감독|신입 편집자|받아쓰기`.
- 항목마다 시각이나 부제를 붙이려면 `data=` 뒤에 JSON 한 덩어리를 쓴다. 다른 키와 섞어도 되고, 겹치면 JSON 쪽 값을 쓴다.
- 값 안에 `&`를 넣으려면 `%26`으로 쓴다. `&`는 키와 키를 나누는 기호라서 그대로 쓰면 값이 잘린다.
- `[대괄호]`로 감싼 낱말은 흰 스티커(검은 글자, 살짝 기울임)로 강조된다. 줄바꿈은 `\n`.
- `at`(시각)은 카드가 시작하고 몇 초 뒤인지다. 받아쓰기의 낱말 시각에서 카드를 얹는 시각을 빼서 넣는다. 안 주면 고르게 나눈다.
- 셸 따옴표: bash·zsh는 JSON이 든 query를 작은따옴표로 감싼다. PowerShell은 바깥을 큰따옴표로 감싸고 JSON 안은 작은따옴표로 쓴다(cards.html이 둘 다 읽는다).

## 1. title — 챕터·라운드 카드 (2.4~3초)

```
python scripts/render_motion.py motion/cards.html 편집/motion/round2.mp4 --dur 2.6 --query "kind=title&label=ROUND 2&title=자막은 [누가] 다나?&sub=받아쓰기부터 CapCut 자막까지 한 번에&n=2&of=5"
```

| 키 | 뜻 |
|---|---|
| `label` | 위의 작은 라벨(`ROUND 2`, `2단계`) |
| `title` | 큰 제목 |
| `sub` | 의미 한 줄 |
| `n`, `of` | 아래 진행 점(`of`개 중 `n`번째) |
| `in` | 제목 등장 방식. `letters`(한 글자씩, 기본) `rise` `blur` `wipe` `push` `flip`. 같은 카드가 여러 번 나오면 회차마다 바꾼다 |

## 2. number — 숫자 굴리기 (3~4초)

```
python scripts/render_motion.py motion/cards.html 편집/motion/time.mp4 --dur 4 --query "kind=number&title=편집 시간&from=30&to=8&unit=시간&at=0.8&sub=혼자 할 때 30시간, 클로드와 함께 8시간&badge=22시간 줄었다"
```

| 키 | 뜻 |
|---|---|
| `to` | 목표 숫자(실제 값). 소수점 자리는 적은 그대로 보인다 |
| `from` | 시작 숫자. 없으면 0부터 굴린다. 있으면 막대가 그만큼에서 줄거나 자라고, 원래 길이가 옅게 남는다 |
| `title`, `unit`, `sub` | 위 라벨, 단위, 아래 설명 |
| `at`, `roll` | 굴리기 시작 시각(기본 0.6초)과 굴리는 시간(기본 1.2초). `at`은 그 숫자를 말하는 순간에 맞춘다 |
| `badge` | 다 굴린 뒤 붙는 스티커 한 장 |
| `fromlabel` | 막대 밑 시작값 앞에 붙는 말(예: `어제`) |
| `min`, `max` | 막대 범위. 95,000 → 100,000처럼 차이가 작으면 `min=90000` |
| `group=0` | 쉼표를 빼고 보인다(연도 등) |

## 3. steps — 한 칸씩 켜지는 단계·팀 (항목 수 × 0.8초 이상)

```
python scripts/render_motion.py motion/cards.html 편집/motion/team.mp4 --dur 8 --query 'kind=steps&data={"title":"내 편집팀","items":[{"name":"감독","sub":"나","at":1.2},{"name":"신입 편집자","sub":"Claude","at":2.0},{"name":"받아쓰기","sub":"Whisper","at":2.8},{"name":"이미지","sub":"ChatGPT","at":3.6},{"name":"모션그래픽","sub":"Claude Code","at":4.4},{"name":"목소리","sub":"ElevenLabs","at":5.2},{"name":"편집실","sub":"CapCut","at":6.0}]}'
```

짧게 쓰기(시각은 `at`에 `|`로):

```
python scripts/render_motion.py motion/cards.html 편집/motion/today.mp4 --dur 5 --query "kind=steps&title=오늘 할 일&items=받아쓰기|컷 편집|자막|효과음&subs=Whisper|cut_plan|subs_shift|CapCut&at=0.9|1.8|2.7|3.6"
```

PowerShell에서 JSON을 쓸 때:

```
python scripts/render_motion.py motion/cards.html 편집/motion/team.mp4 --dur 5 --query "kind=steps&data={'title':'내 편집팀','items':[{'name':'감독','sub':'나','at':1.0},{'name':'신입 편집자','sub':'Claude','at':2.0},{'name':'받아쓰기','sub':'Whisper','at':3.0}]}"
```

| 키 | 뜻 |
|---|---|
| `title` | 위 진행 알약의 글자 |
| `items`, `subs`, `at` | 칸 이름, 칸 아래 작은 글자, 켜지는 시각. 3~8개 |
| `layout=list` | 격자 대신 세로 목록 |
| `cols` | 격자 열 수(기본: 4개 이하면 한 줄, 그보다 많으면 두 줄) |

## 4. verdict — AI가 됩니다 / 아직 사람 몫 (5~8초)

```
python scripts/render_motion.py motion/cards.html 편집/motion/verdict.mp4 --dur 6 --query "kind=verdict&title=편집 13단계, 어디까지 AI가?&ai=컷 편집|자막 받아쓰기|효과음 배치|모션 카드&human=무엇을 찍을지|마지막 판단"
```

| 키 | 뜻 |
|---|---|
| `ai`, `human` | 왼쪽·오른쪽 항목(각 6개까지). JSON이면 `[{"t":"컷 편집","at":1.0}, ...]` |
| `at` | 항목이 나오는 시각. 왼쪽 항목 다음 오른쪽 항목 순서로 `|`로 나눈다 |
| `left`, `right` | 칸 제목(기본 `AI가 됩니다`, `아직 사람 몫`) |
| `title` | 맨 위 제목(없어도 된다) |

## 5. score — 점수판 (2.6~3.2초)

```
python scripts/render_motion.py motion/cards.html 편집/motion/score_r3.mp4 --dur 3.2 --query "kind=score&title=3라운드 결과&n=3&of=5&names=클로드|GPT|제미나이&scores=3|2|1&win=클로드"
```

| 키 | 뜻 |
|---|---|
| `names`, `scores` | 2~3명과 **이번 라운드가 끝난 뒤** 점수. JSON이면 `"players":[{"name":"클로드","score":3}, ...]` |
| `win` | 이긴 쪽(이름 또는 1·2·3번째). 그 점수가 `add`(기본 1)만큼 낮은 값에서 올라가며 한 번 커졌다 돌아온다 |
| `at` | 점수가 오르는 시각(기본 1.4초) |
| `title`, `n`, `of` | 위 알약 글자와 라운드 진행 점 |

## 6. compare — 좌우 고정 비교 (3~5초)

```
python scripts/render_motion.py motion/cards.html 편집/motion/length.mp4 --dur 4 --query "kind=compare&title=영상 길이&left=클로드 초벌&lv=14&lu=분&ln=말 그대로 다 살린 첫 편집&right=최종&rv=12&ru=분&rn=사람이 2분 덜어 냄&win=right"
```

| 키 | 뜻 |
|---|---|
| `left`, `right` | 양쪽 라벨 |
| `lv`, `rv` | 값. 숫자면 0부터 굴리고, `12:14`처럼 글자면 그대로 보인다 |
| `lu`, `ru` (또는 `unit`) | 단위 |
| `ln`, `rn` | 아래 설명 한 줄 |
| `lat`, `rat` | 값이 나오는 시각(기본 0.9초, 1.6초) |
| `limg`, `rimg` | 값 위에 넣을 그림. cards.html이 있는 폴더 기준 경로라서, 그림을 쓸 때는 cards.html을 그림 폴더(예: `편집/motion/`)에 복사해 그 사본을 렌더한다 |
| `mid` | 가운데 표시(기본 `→`, 대결이면 `VS`) |
| `win` | `left` 또는 `right`. 그쪽이 주황으로 켜지고 반대쪽은 옅어진다 |

JSON으로 쓰면: `data={"title":"영상 길이","left":{"label":"클로드 초벌","value":14,"unit":"분","note":"..."},"right":{"label":"최종","value":12,"unit":"분"},"win":"right"}`

## 브라우저로 미리 보기

`motion/cards.html?kind=number&title=편집 시간&from=30&to=8&unit=시간&play=1&dur=4` 를 브라우저 주소창에 열면 반복 재생된다. `play`를 빼면 마지막 장면이 보인다. 미리 보기용이고, 영상은 render_motion.py로 만든다.
