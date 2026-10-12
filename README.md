# threads-auto (1단계: 텔레그램으로 초안 받기)

살림 고수 캐릭터가 핫이슈를 골라 100자 글 + 사진 + 쿠팡 후보 3개를 만들어
텔레그램으로 보내 줍니다. **1단계에서는 쓰레드에 게시하지 않아요.**

## 파일 구성
| 파일 | 하는 일 |
|---|---|
| `prompts/persona.md` | 캐릭터·말투·금지 주제 (여기만 고치면 글 성격이 바뀜) |
| `src/trends.py` | 구글 트렌드·구글 뉴스 (+ 네이버·유튜브는 키가 있을 때만) |
| `src/writer.py` | Claude가 이슈 선택 + 글 작성 |
| `src/images.py` | 제미나이 사진 생성, 실패 시 Pexels |
| `src/coupang.py` | 쿠팡 파트너스 상품 후보 3개 검색 |
| `src/telegram.py` | 텔레그램 전송 |
| `src/make_draft.py` | 위 순서대로 실행 |
| `.github/workflows/draft.yml` | 매일 06:30, 18:30 자동 실행 |

## 1단계에 필요한 GitHub Secrets
`ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `PEXELS_API_KEY`,
`COUPANG_ACCESS_KEY`, `COUPANG_SECRET_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`

(선택) `NAVER_CLIENT_ID`, `NAVER_CLIENT_SECRET`, `YOUTUBE_API_KEY`

## 바로 시험해 보기
GitHub 저장소 → **Actions** 탭 → **초안 만들기** → **Run workflow**
