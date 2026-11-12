# 처음 사용할 때

Codex는 스킬 폴더와 영상 작업 폴더를 구분한다. 스크립트·HTML 템플릿은 스킬 폴더에서 읽고, 원본과 `편집/` 결과는 영상 작업 폴더에 둔다. 설치 위치와 준비물은 [README](../README.md)를 참조한다.

## 준비

1. Codex에서 영상 파일이 있는 작업 폴더를 연다. 대본과 별도 마이크 녹음이 있으면 함께 둔다.
2. Python 3.10 이상, FFmpeg/FFprobe, `scripts/requirements.txt`의 패키지, CapCut 데스크톱을 준비한다. 실행 가능한 Python을 찾는다. WindowsApps의 `python.exe` 별칭이 실패하면 실제 Python 실행 파일을 사용한다.
3. 기본 영상·자막 초안에는 영상 클립과 자막 텍스트가 있는 CapCut 프로젝트를 템플릿으로 쓴다. 별도 음성·효과음·BGM까지 넣으려면 로컬 파일 오디오 클립도 포함한다. 기존 프로젝트와 원본은 덮어쓰지 않는다.
4. 스킬의 `scripts/doctor.py`를 읽기 전용으로 실행한다. Codex의 격리된 `%LOCALAPPDATA%` 때문에 CapCut 프로젝트 경로가 자동 검색되지 않으면 `--capcut-dir <실제 경로>`를 전달한다.
5. 모션 카드를 쓸 경우 Playwright Chromium과 Pretendard 글꼴을 확인한다. GPU는 없어도 되며 CPU 받아쓰기는 더 느리다. 기본 Whisper 모델은 첫 사용 때 다운로드된다.

## 첫 1분 영상

1. 1분 정도의 말하는 영상을 작업 폴더에 둔다.
2. Codex에 `$smartdaddy-video-edit`를 지정하며 “버벅인 부분을 정리하고 의미 단위 자막을 달아 CapCut 초벌을 만들어 줘”라고 요청한다.
3. Codex가 만든 `편집/02_cut/cuts.md`의 삭제 내용과 확인 필요 지점을 읽고, `편집/preview.mp4`를 본다.
4. CapCut 프로젝트 등록이 필요하면 CapCut을 완전히 종료한다. Codex는 새 이름으로 등록하고 기존 프로젝트를 보존해야 한다.
5. 마음에 들지 않는 곳은 시각과 함께 말한다. 예: “37초에 같은 말을 두 번 했어. 앞의 것을 자르고 마지막 테이크를 남겨 줘.”
6. 다음 영상에도 적용할 규칙은 “오늘 고친 것을 스킬의 `내 규칙`에 저장해 줘”라고 요청한다.

## 자주 걸리는 문제

| 증상 | 확인할 것 |
|---|---|
| `python`을 실행할 수 없음 | 실제 Python 경로 또는 작업 폴더의 가상환경 사용 |
| FFmpeg가 없음 | FFmpeg/FFprobe 설치와 PATH 확인. 새 터미널에서 재점검 |
| CapCut 프로젝트를 못 찾음 | `doctor.py --capcut-dir`에 실제 프로젝트 폴더 지정 |
| 프로젝트 조립 실패 | `doctor.py --require-template basic`으로 영상·자막 템플릿을 확인. 별도 음성·효과음·BGM이면 `audio`로 로컬 오디오도 확인 |
| 받아쓰기가 느림 | GPU가 없다면 CPU로 실행하며 긴 영상은 더 작은 모델을 고려 |
| 효과음·줌 시각이 어긋남 | 조립 출력의 `[못 넣음]`과 `_timeline.json`을 보고 `overlays.json`의 `word` 수정 |
| 말 끝이 잘림 | `cuts.md`에서 해당 구간을 찾고 컷을 보호한 뒤 다시 검사 |

초벌은 사람이 CapCut에서 검토하고 마지막 컷과 구성을 결정할 수 있도록 클립을 나누어 제공한다.
