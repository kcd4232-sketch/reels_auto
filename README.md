# reels_auto — 릴스 영상 편집기

원본 영상과 대본을 작업별로 묶고, 기존 ElevenLabs 목소리로 나레이션과 발화 시각에 맞춘 자막을 만들어 세로 MP4로 출력하는 로컬 편집기입니다.

## 주요 기능

- 영상 드래그 앤 드롭, 여러 원본을 한 작업으로 묶기
- 대본 붙여넣기 또는 Markdown 첨부, 배경음·엔딩 이미지 첨부
- 선택한 작업을 차례로 처리하고 실제 합성 진행률·완료 시각 표시
- 완료 영상 미리보기, 완료 목록 숨기기·표시 및 설정 기억
- 짙은 네이비 배경과 Light Green 포인트, 녹색 입력·첨부 영역
- 기존 나레이션 재사용, Paperlogy 자막과 상단 훅

## 설치

Windows와 Python 3.11 이상을 권장합니다. Python 3.13에서 확인했습니다.
FFmpeg와 FFprobe가 PATH에 있어야 하며 FFmpeg는 libass 자막 필터를 지원해야 합니다.
자막에 사용하는 Paperlogy 7Bold·9Black 글꼴도 PC에 설치하세요.
SVG 엔딩 이미지를 사용하려면 Chrome 또는 Edge가 필요합니다.

```powershell
git clone https://github.com/kcd4232-sketch/reels_auto.git
cd reels_auto
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env.local
Copy-Item elevenlabs_voice.example.json elevenlabs_voice.json
```

`.env.local`에 본인의 `ELEVENLABS_API_KEY`를 입력하고, `elevenlabs_voice.json`의 `voice_id`를 본인 계정에 이미 등록한 목소리 ID로 바꾸세요. 기존 프로젝트를 옮기는 경우 기존 설정 파일을 로컬로 복사해 재사용합니다. 새 복제 목소리를 만들 필요는 없습니다. 이 두 설정 파일은 Git에 포함하지 않습니다.

## 실행

Windows 탐색기에서 **영상_편집_작업보드.cmd**를 더블클릭하거나 다음 명령을 실행합니다.

```powershell
.\.venv\Scripts\python.exe scripts\job_board.py
```

브라우저에서 `http://127.0.0.1:8765/`가 열립니다.

1. **원본 영상 추가**로 영상을 선택합니다.
2. 작업을 눌러 대본을 붙여넣고 **대본 저장**을 누릅니다. 배경음과 엔딩 이미지는 선택 사항입니다.
3. 작업 체크 후 **선택 작업 편집**을 누릅니다.
4. 작업 목록 오른쪽 **완료 작업 표시**를 끄면 완료 작업이 숨겨집니다. 숨긴 작업은 실행 선택에서도 해제됩니다.

새 나레이션 생성에는 ElevenLabs 사용량이 발생합니다. 이미 생성한 음성을 재사용할 수도 있습니다. 상세 사용법은 [작업보드_사용법.md](작업보드_사용법.md)를 참고하세요.

## 파일 구성

| 경로 | 역할 |
| --- | --- |
| `scripts/job_board.py` | 로컬 서버·작업 큐 |
| `scripts/elevenlabs_reels.py` | 나레이션·발화 시각 |
| `scripts/render_reel.py` | FFmpeg 합성·자막·엔딩 |
| `scripts/create_reel.py` | 명령행 일괄 실행 |
| `ui/` | 작업 보드 화면 |
| `config/` | 자막 및 대시보드 스타일 |
| `tests/` | 입력 처리 회귀 테스트 |
| `reels-caption-motion/`, `smartdaddy-video-edit/` | 기존 저장소의 편집 스킬 |

원본·음성·개인 대본·로고·작업 기록·결과물은 저장소에 포함하지 않습니다. 결과는 `편집/elevenlabs/`, 작업 기록과 첨부 복사본은 `편집/job_board/`에 자동 저장됩니다. 프로젝트 기본 대본을 사용하려면 `대본/대본.md`를 직접 만드세요. 기본 엔딩은 COSMICO 텍스트이므로 다른 브랜드는 엔딩 이미지를 첨부하세요.

명령행 `create_reel.py`는 `원본/`, `대본/대본.md`, 기존 `elevenlabs_voice.json`을 준비한 뒤 사용합니다. 목소리 설정이 없을 때 음성 샘플로 복제를 시도하는 경로가 있으므로 기존 목소리 설정부터 준비하세요.

## 확인

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

## 디자인 출처

- Light Green: Alexander VQ, https://tweakcn.com/themes/cmlhfpjhw000004l4f4ax3m7z
- UI 정리 지침: unslop, Damir Sokolovsky, CC BY 4.0, https://github.com/heydamir/unslop

글꼴과 외부 서비스는 각 제공자의 이용 조건을 따릅니다.
