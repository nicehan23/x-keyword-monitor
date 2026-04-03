# 🚀 공부법 트윗 자동생성 시스템

> 트렌딩 트윗을 분석하여 공부법 관련 트윗(메인 + 스레드)을 자동 생성하고, X(트위터)에 자동 포스팅하는 시스템입니다.

## ✨ 주요 기능

- **트렌드 수집**: X에서 공부법 관련 인기 트윗 자동 크롤링 (매일 23:00)
- **AI 트윗 생성**: Claude AI가 트렌드를 분석하여 메인 트윗 + 3~5개 스레드 자동 생성
- **AI 품질 검수**: 포스팅 전 AI가 자동으로 품질 검토
- **자동 포스팅**: 하루 4회 자동 포스팅 (08:00, 17:00, 18:00, 20:00 KST) — ⚠️ 2026-03-30부터 잠정 중단 (X API 토큰 절약)
- **인게이지먼트 추적**: RT, 좋아요, 조회수 등 자동 수집 (매일 07:30)
- **대시보드 2종**:
  - 트윗 크롤러 대시보드: [dashboard.html](https://nicehan23.github.io/x-keyword-monitor/dashboard.html) — 수집된 트윗 목록, 최근 7일 RT 기준 Top 5, 키워드별 필터, 시간대별 차트
  - 자동생성 대시보드: [tweet-dashboard.html](https://nicehan23.github.io/x-keyword-monitor/tweet-dashboard.html) — AI 생성 트윗 관리, 포스팅 상태, 인게이지먼트

---

## 📋 사전 준비 (API 키 발급)

### 1. X (Twitter) API 키

1. [X Developer Portal](https://developer.x.com/en/portal/dashboard) 접속
2. **Projects & Apps** → **+ Create App**
3. **User authentication settings** → **Set up**
   - App permissions: **Read and Write** 선택
   - Type of App: **Web App**
   - Callback URL: `https://example.com`
4. **Keys and tokens** 탭에서 복사:
   - Bearer Token
   - API Key (Consumer Key)
   - API Secret (Consumer Secret)
   - Access Token
   - Access Token Secret

> ⚠️ Access Token은 **Read and Write 권한 설정 후에** Regenerate 해야 합니다!

### 2. Claude API 키

1. [Anthropic Console](https://console.anthropic.com) 접속
2. **API Keys** → **Create Key**

---

## 🔧 설치 방법 (3분 소요)

터미널(Terminal.app)을 열고 아래 **한 줄**을 붙여넣으세요:
```bash
curl -sL https://raw.githubusercontent.com/nicehan23/x-keyword-monitor/main/setup.sh | bash
```

설치 중 API 키를 입력하라는 메시지가 나옵니다.

### 수동 설치
```bash
git clone https://github.com/nicehan23/x-keyword-monitor.git
cd x-keyword-monitor
pip3 install anthropic supabase python-dotenv tweepy requests --break-system-packages
cp .env.example .env
nano .env  # 키 입력 후 Ctrl+O → Enter → Ctrl+X
python3 generate_and_post.py --dry-run
```

---

## 📌 사용법

| 명령어 | 설명 |
|:-------|:-----|
| `python3 generate_and_post.py --dry-run` | 테스트 (포스팅 안 함) |
| `python3 generate_and_post.py` | 즉시 포스팅 |
| `python3 fetch_engagement.py` | 인게이지먼트 수동 업데이트 |
| `crontab -l` | 스케줄 확인 |

### 대시보드

- 크롤러 대시보드: [dashboard.html](https://nicehan23.github.io/x-keyword-monitor/dashboard.html) — 수집 트윗 & Top 5 (최근 7일 RT 기준)
- 자동생성 대시보드: [tweet-dashboard.html](https://nicehan23.github.io/x-keyword-monitor/tweet-dashboard.html) — AI 생성 트윗 관리

---

## ⏰ 자동 실행 스케줄

| 시간 | 작업 |
|:----:|:-----|
| 23:00 | 트윗 수집 (크롤링) |
| 23:00 | 친소 자동 좋아요 (`like_tchinso.py`) |
| 07:30 | 인게이지먼트 업데이트 |
| 08:00 | ~~트윗 생성 + 포스팅~~ (잠정 중단) |
| 17:00 | ~~트윗 생성 + 포스팅~~ (잠정 중단) |
| 18:00 | ~~트윗 생성 + 포스팅~~ (잠정 중단) |
| 20:00 | ~~트윗 생성 + 포스팅~~ (잠정 중단) |

> 💡 Mac 잠자기 모드에서는 자동 실행 안 됨. **시스템 설정 → 에너지 → 네트워크 액세스를 위해 깨우기** 켜기

---

## ❓ 문제 해결

- **403 Forbidden** → X Developer Portal에서 Access Token Regenerate
- **ModuleNotFoundError** → `pip3 install anthropic supabase python-dotenv tweepy requests --break-system-packages`
- **TypeError: unsupported operand** → `sed -i '' '1s/^/from __future__ import annotations\n/' ~/x-keyword-monitor/generate_and_post.py`
- **자동 포스팅 안 됨** → Mac 잠자기 확인 + `crontab -l`

---

## 📁 파일 구조
```
x-keyword-monitor/
├── .env                    # API 키 (공유 금지!)
├── .env.example            # API 키 템플릿
├── setup.sh                # 원클릭 설치 스크립트
├── collect_tweets.py       # X 트윗 수집기
├── generate_and_post.py    # 트윗 생성 + 포스팅
├── tweet_templates.py      # AI 프롬프트 템플릿
├── fetch_engagement.py     # 인게이지먼트 수집기
├── dashboard.html          # 크롤러 대시보드 (수집 트윗, Top 5)
├── tweet-dashboard.html    # 자동생성 대시보드 (AI 트윗, 포스팅)
└── cron.log                # 실행 로그
```
