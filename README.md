# AI 트렌드 레이더

Claude·Gemini 스킬과 기능 변화를 매일 자동으로 수집합니다. 남규님 업무(①PDF→Raw data, ②보고 덱, ③리서치·검증, ④회의록)와 관련된 것만 골라 텔레그램으로 알립니다.

## 무엇을 하나

| 시각 (KST) | 동작 |
|---|---|
| 매일 07:07 | 지난 30시간을 수집합니다. 관련도·반응 기준을 넘은 항목만 최대 5건 텔레그램으로 보냅니다. 이미 보낸 항목은 다시 보내지 않습니다. |
| 월요일 07:41 | 지난 7일 상위 항목과 워치리스트 Stars 증가를 텔레그램으로 보냅니다. |
| 월요일 08:00 전후 | Claude 예약 작업이 이 기록과 공식 출처를 읽고 분석 보고를 작성합니다. 보고는 Drive `AI Weekly`에 저장되고 이메일로도 옵니다. |

## 수집 출처와 화제도 지표 (무료)

| 출처 | 화제도 지표 | 알림 기준 (config.json) |
|---|---|---|
| Hacker News (Algolia API) | 점수, 댓글 수 | `hn_points` 50 |
| Reddit: r/ClaudeAI, r/ClaudeCode, r/Anthropic, r/GeminiAI, r/Bard, r/notebooklm | 하루 상위 글의 점수, 댓글 수 | `reddit_score` 150. 점수를 못 읽고 RSS로만 받으면 하루 순위 3위 이내 |
| GitHub Trending (일간·주간) | 오늘 또는 이번 주에 받은 Stars | 일간 150, 주간 500 |
| GitHub 검색 (최근 7일 새 스킬 저장소) | 누적 Stars와 하루 증가 속도. 속도는 이틀째부터 계산 | 150 stars 또는 하루 +50 |
| GitHub 워치리스트 릴리스 | 정식 새 버전 (nightly·preview·rc 제외) | 릴리스가 나오면 알림. Claude Code·Gemini CLI처럼 매일 나오는 저장소는 릴리스 노트에 업무 테마(PDF·덱·리서치·회의록)가 있을 때만 알림 |
| RSS: GeekNews, Google Workspace Updates | 공식 변경 | 관련 항목이면 알림 |

모든 출처에 공통 조건이 있습니다. Claude·Gemini 업무 관련도 2 이상인 항목만 알림 대상이 됩니다. 커뮤니티 글은 Claude·Gemini 언급이 있어야 합니다.

**Reddit 주의:** 2026-10-21 첫 실행 결과, GitHub Actions에서 공개 `.json`은 6곳 모두 403으로 막혔습니다. RSS는 r/ClaudeAI와 r/notebooklm 두 곳에서만 받아져서 점수 없이 순위만 씁니다. 2025년 11월부터 공식 API는 사전 승인제로 바뀌었고, 개인 용도로는 승인을 받기 어렵습니다. 그래서 로그인 없는 공개 `.json`을 쓰고, 막히면 RSS로 넘어갑니다. 클라우드 서버 IP는 막힐 때가 많고, 그 경우 '실패'로 기록됩니다. 첫 실행 기록에서 실제로 되는지 확인합니다.

X와 Threads는 수집하지 않습니다. 궁금한 게시물이 있으면 대화창에 직접 공유해 주세요.

## 설정 (한 번만)

1. **텔레그램 봇 만들기**
   - 텔레그램에서 @BotFather에게 `/newbot`을 보냅니다.
   - 봇을 만들면 토큰을 받습니다.
   - 만든 봇에게 아무 메시지나 한 번 보냅니다.
   - 브라우저에서 `https://api.telegram.org/bot<토큰>/getUpdates`를 엽니다.
   - 결과에서 `chat.id` 숫자를 확인합니다.
2. **GitHub 저장소 Secrets 등록**
   - 저장소에서 Settings → Secrets and variables → Actions로 들어갑니다.
   - `TELEGRAM_BOT_TOKEN`과 `TELEGRAM_CHAT_ID` 두 개를 추가합니다.
   - 토큰은 이 저장소 파일이나 대화창에 붙여 넣지 마세요.
3. **첫 실행**
   - Actions 탭에서 `ai-trend-radar`를 엽니다.
   - Run workflow를 누릅니다.

## 조정

키워드, 테마, 알림 기준, 워치리스트는 `config.json`에서만 바꿉니다.

- `alert.min_relevance`: 관련도 하한
- `hn_points`, `github_new_repo_stars` 등: 출처별 반응 기준

알림이 너무 많으면 기준값을 올리고, 너무 적으면 내립니다.

## 기록

- `data/daily/YYYY-MM-DD.json`: 수집 항목, 출처별 성공·실패, 알림한 항목
- `data/stars.json`: 워치리스트 Stars 일별 스냅숏. 증가율은 7일 이상 쌓인 뒤에만 계산합니다.
- `data/seen.json`: 중복 알림 방지
