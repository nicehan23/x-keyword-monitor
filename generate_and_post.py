from __future__ import annotations
#!/usr/bin/env python3
"""
공부법 트윗 자동생성 & 포스팅 파이프라인
- Supabase에서 트렌드 데이터 가져오기
- Claude API로 트윗 생성
- X API로 자동 포스팅
"""

import os
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

import anthropic
from supabase import create_client
from tweet_templates import get_tweet_prompt, get_thread_prompt

# ──────────────────────────────────────────────
# 로깅 설정
# ──────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("tweet_generator.log", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# 환경변수 로드
# ──────────────────────────────────────────────
from dotenv import load_dotenv
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

# X API OAuth 1.0a (포스팅용 — 없으면 생성만 하고 포스팅 스킵)
X_API_KEY = os.getenv("X_API_KEY")
X_API_SECRET = os.getenv("X_API_SECRET")
X_ACCESS_TOKEN = os.getenv("X_ACCESS_TOKEN")
X_ACCESS_TOKEN_SECRET = os.getenv("X_ACCESS_TOKEN_SECRET")

# 설정
MAX_TWEETS_PER_DAY = 4
TREND_LOOKBACK_DAYS = 7
TREND_TOP_N = 20
SIMILARITY_THRESHOLD = 0.7  # 중복 방지 임계값
QANDA_MENTION_EVERY_N = 4   # N번째 트윗마다 콴다 자연스럽게 언급
THREAD_MIN = 3              # 스레드 최소 답글 수
THREAD_MAX = 5              # 스레드 최대 답글 수


def can_post_tweets() -> bool:
    """X API 포스팅에 필요한 OAuth 키가 모두 있는지 확인"""
    return all([X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_TOKEN_SECRET])


# ──────────────────────────────────────────────
# Step 1: Supabase에서 트렌드 데이터 가져오기
# ──────────────────────────────────────────────
def fetch_trending_tweets(supabase) -> list[dict]:
    """최근 N일간 반응(리트윗+좋아요)이 높은 트윗 TOP N개 가져오기"""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=TREND_LOOKBACK_DAYS)).isoformat()

    response = (
        supabase.table("tweets")
        .select("tweet_id, text, author_username, like_count, retweet_count, impression_count, created_at, keyword")
        .gte("created_at", cutoff)
        .order("retweet_count", desc=True)
        .limit(TREND_TOP_N)
        .execute()
    )

    tweets = response.data or []
    log.info(f"트렌드 트윗 {len(tweets)}개 가져옴 (최근 {TREND_LOOKBACK_DAYS}일)")
    return tweets


def fetch_threads_for_tweets(supabase, tweet_ids: list[str]) -> dict[str, list[dict]]:
    """Top 트윗들의 스레드를 가져오기. {parent_tweet_id: [thread_tweets...]} 반환"""
    if not tweet_ids:
        return {}

    try:
        response = (
            supabase.table("tweet_threads")
            .select("parent_tweet_id, text, position")
            .in_("parent_tweet_id", tweet_ids)
            .order("position", desc=False)
            .execute()
        )

        threads = {}
        for row in (response.data or []):
            pid = row["parent_tweet_id"]
            if pid not in threads:
                threads[pid] = []
            threads[pid].append(row)

        thread_count = sum(len(v) for v in threads.values())
        log.info(f"스레드 {len(threads)}개 트윗의 {thread_count}개 답글 가져옴")
        return threads

    except Exception:
        log.warning("tweet_threads 테이블 조회 실패 — 스레드 없이 진행")
        return {}


def fetch_recent_generated(supabase, days: int = 30) -> list[str]:
    """최근 N일간 생성된 트윗 텍스트 가져오기 (중복 방지용)"""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    try:
        response = (
            supabase.table("generated_tweets")
            .select("tweet_text")
            .gte("created_at", cutoff)
            .execute()
        )
        return [row["tweet_text"] for row in (response.data or [])]
    except Exception:
        log.warning("generated_tweets 테이블이 없거나 비어있음 — 중복 검사 스킵")
        return []


def get_today_post_count(supabase) -> int:
    """오늘 이미 포스팅된 트윗 수 확인"""
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0).isoformat()

    try:
        response = (
            supabase.table("generated_tweets")
            .select("id", count="exact")
            .gte("created_at", today_start)
            .eq("status", "posted")
            .execute()
        )
        return response.count or 0
    except Exception:
        return 0


def get_total_post_count(supabase) -> int:
    """전체 포스팅 수 확인 (콴다 언급 빈도 조절용)"""
    try:
        response = (
            supabase.table("generated_tweets")
            .select("id", count="exact")
            .execute()
        )
        return response.count or 0
    except Exception:
        return 0


# ──────────────────────────────────────────────
# Step 2: Claude API로 트윗 생성
# ──────────────────────────────────────────────
def generate_tweet(trending_tweets: list[dict], previous_tweets: list[str], include_qanda: bool, threads: dict = None) -> str:
    """Claude API를 사용하여 공부법 트윗 생성 (스레드 컨텍스트 포함)"""
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    threads = threads or {}

    # 트렌드 트윗 + 스레드를 텍스트로 정리
    trends_text = ""
    for i, t in enumerate(trending_tweets[:15], 1):
        likes = t.get("like_count", 0) or 0
        rts = t.get("retweet_count", 0) or 0
        trends_text += f"{i}. [♥{likes} 🔁{rts}] {t['text'][:200]}\n"

        # 해당 트윗에 스레드가 있으면 함께 표시
        tweet_id = t.get("tweet_id", "")
        if tweet_id and tweet_id in threads:
            for thread_tweet in threads[tweet_id]:
                pos = thread_tweet.get("position", 0)
                thread_text = thread_tweet.get("text", "")[:200]
                trends_text += f"   └ 스레드 {pos}: {thread_text}\n"

    # 이전 생성 트윗 (중복 방지)
    prev_text = ""
    if previous_tweets:
        recent_5 = previous_tweets[-5:]
        prev_text = "\n".join(f"- {t[:100]}" for t in recent_5)

    prompt = get_tweet_prompt(trends_text, prev_text, include_qanda)

    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=300,
        messages=[{"role": "user", "content": prompt}],
    )

    tweet_text = response.content[0].text.strip()

    # 길이 초과 방지 (한글 기준 140자 ≈ 280 bytes)
    if len(tweet_text) > 280:
        tweet_text = tweet_text[:277] + "..."

    log.info(f"생성된 트윗: {tweet_text}")
    return tweet_text


# ──────────────────────────────────────────────
# Step 2.5: AI 리뷰 (포스팅 전 품질 검증)
# ──────────────────────────────────────────────
def review_tweet(tweet_text: str) -> dict:
    """
    생성된 트윗을 포스팅 전에 AI가 검토.
    반환: {"pass": True/False, "reason": "...", "suggestion": "..."}
    """
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    review_prompt = f"""당신은 교육 콘텐츠 SNS 마케팅 품질 검수 담당자입니다.
아래 트윗을 포스팅해도 되는지 검토해주세요.

[중요] 이것은 SNS 트윗입니다. 논문이 아닙니다.
- 일상적인 표현("효과 있음", "성적 오름" 등)은 SNS 화법으로 허용합니다.
- "~하면 좋다", "~하면 효율적이다" 같은 일반적 공부 조언은 PASS입니다.
- 명백히 틀린 정보(예: "밤새 공부가 최고다")만 사실 오류로 판단하세요.

[검토할 트윗]
{tweet_text}

[FAIL 기준 — 아래에 해당할 때만 FAIL]
1. 명백한 사실 오류: 건강에 해롭거나 학습에 역효과를 주는 잘못된 정보
2. 브랜드 리스크: 욕설, 비하, 차별적 표현
3. 노골적 광고: "지금 당장 다운로드", "앱 설치하세요" 같은 직접적 광고 문구
4. 심각한 맞춤법 오류: 읽기 어려운 수준의 오타 (사소한 건 무시)
5. 민감한 내용: 정치, 종교, 차별 관련 내용
6. 길이 초과: 280자 초과

[PASS 기준 — 아래에 해당하면 PASS]
- 일반적으로 통용되는 공부 팁/조언
- 약간의 과장("집중력 확 오름")은 SNS 화법으로 허용
- 포모도로, 오답노트 등 널리 알려진 학습법 언급

[출력 형식 — JSON만 출력하세요]
{{"pass": true 또는 false, "reason": "판단 이유 (1줄)", "suggestion": "FAIL일 경우 수정 제안 (PASS면 빈 문자열)"}}"""

    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            messages=[{"role": "user", "content": review_prompt}],
        )

        result_text = response.content[0].text.strip()

        # JSON 파싱 (```json ... ``` 감싸진 경우 처리)
        if "```" in result_text:
            result_text = result_text.split("```")[1]
            if result_text.startswith("json"):
                result_text = result_text[4:]
            result_text = result_text.strip()

        result = json.loads(result_text)
        passed = result.get("pass", False)
        reason = result.get("reason", "")
        suggestion = result.get("suggestion", "")

        if passed:
            log.info(f"✅ 리뷰 PASS: {reason}")
        else:
            log.warning(f"❌ 리뷰 FAIL: {reason}")
            if suggestion:
                log.warning(f"   💡 수정 제안: {suggestion}")

        return result

    except Exception as e:
        log.error(f"리뷰 중 오류 발생: {e} — 안전을 위해 FAIL 처리")
        return {"pass": False, "reason": f"리뷰 오류: {e}", "suggestion": ""}


# ──────────────────────────────────────────────
# Step 3: 간단한 중복 검사
# ──────────────────────────────────────────────
def is_too_similar(new_tweet: str, existing_tweets: list[str]) -> bool:
    """자카드 유사도 기반 간단한 중복 검사"""
    if not existing_tweets:
        return False

    new_words = set(new_tweet.split())
    for existing in existing_tweets:
        existing_words = set(existing.split())
        if not new_words or not existing_words:
            continue
        intersection = new_words & existing_words
        union = new_words | existing_words
        similarity = len(intersection) / len(union)
        if similarity > SIMILARITY_THRESHOLD:
            log.warning(f"중복 감지 (유사도 {similarity:.2f}): {new_tweet[:50]}...")
            return True
    return False


# ──────────────────────────────────────────────
# Step 4: X API로 포스팅
# ──────────────────────────────────────────────
def post_to_x(tweet_text: str) -> "str | None":
    """X API v2로 트윗 포스팅. 성공 시 tweet_id 반환"""
    if not can_post_tweets():
        log.warning("⚠️  X OAuth 키가 설정되지 않아 포스팅을 건너뜁니다.")
        log.info("포스팅하려면 .env에 X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_TOKEN_SECRET를 추가하세요.")
        return None

    try:
        import tweepy

        client = tweepy.Client(
            consumer_key=X_API_KEY,
            consumer_secret=X_API_SECRET,
            access_token=X_ACCESS_TOKEN,
            access_token_secret=X_ACCESS_TOKEN_SECRET,
        )

        response = client.create_tweet(text=tweet_text)
        tweet_id = response.data["id"]
        log.info(f"✅ 포스팅 완료! Tweet ID: {tweet_id}")
        log.info(f"   → https://x.com/i/web/status/{tweet_id}")
        return tweet_id

    except Exception as e:
        log.error(f"❌ 포스팅 실패: {e}")
        return None


# ──────────────────────────────────────────────
# Step 4.5: 스레드 생성 + 포스팅
# ──────────────────────────────────────────────
def generate_thread_replies(main_tweet: str, include_qanda: bool) -> list[str]:
    """메인 트윗에 대한 스레드 답글 3~5개 생성"""
    import random
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    num_replies = random.randint(THREAD_MIN, THREAD_MAX)
    prompt = get_thread_prompt(main_tweet, num_replies, include_qanda)

    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1000,
        messages=[{"role": "user", "content": prompt}],
    )

    raw_text = response.content[0].text.strip()

    # ---로 구분된 답글 파싱
    replies = [r.strip() for r in raw_text.split("---") if r.strip()]

    # 길이 초과 방지
    replies = [r[:280] for r in replies]

    # 최소 3개, 최대 5개 보장
    if len(replies) < THREAD_MIN:
        log.warning(f"스레드 답글이 {len(replies)}개로 부족 — 재생성 필요")
        return []
    replies = replies[:THREAD_MAX]

    log.info(f"🧵 스레드 {len(replies)}개 답글 생성 완료")
    for i, r in enumerate(replies, 1):
        log.info(f"   스레드 {i}: {r[:60]}...")

    return replies


def post_thread_to_x(main_tweet_id: str, replies: list[str]) -> list[str]:
    """메인 트윗에 스레드 답글 포스팅. 반환: 포스팅된 tweet_id 목록"""
    if not can_post_tweets():
        log.warning("⚠️  X OAuth 키가 없어 스레드 포스팅 건너뜀")
        return []

    try:
        import tweepy
        client = tweepy.Client(
            consumer_key=X_API_KEY,
            consumer_secret=X_API_SECRET,
            access_token=X_ACCESS_TOKEN,
            access_token_secret=X_ACCESS_TOKEN_SECRET,
        )

        posted_ids = []
        reply_to_id = main_tweet_id

        for i, reply_text in enumerate(replies, 1):
            response = client.create_tweet(
                text=reply_text,
                in_reply_to_tweet_id=reply_to_id,
            )
            new_id = response.data["id"]
            posted_ids.append(new_id)
            reply_to_id = new_id  # 다음 답글은 이 답글에 달림 (스레드 체인)
            log.info(f"   🧵 스레드 {i}/{len(replies)} 포스팅 완료: {new_id}")

        return posted_ids

    except Exception as e:
        log.error(f"❌ 스레드 포스팅 실패: {e}")
        return []


# ──────────────────────────────────────────────
# Step 5: Supabase에 로그 저장
# ──────────────────────────────────────────────
def save_generated_tweet(supabase, tweet_text: str, tweet_id: str | None, source_trends: list[dict]):
    """생성/포스팅 결과를 Supabase에 저장"""
    status = "posted" if tweet_id else "generated"

    record = {
        "tweet_text": tweet_text,
        "tweet_id": tweet_id,
        "status": status,
        "source_trends": json.dumps([t.get("text", "")[:100] for t in source_trends[:5]], ensure_ascii=False),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    try:
        supabase.table("generated_tweets").insert(record).execute()
        log.info(f"📝 로그 저장 완료 (status: {status})")
    except Exception as e:
        log.error(f"로그 저장 실패: {e}")
        # 로컬 백업
        backup_path = Path("posted_tweets.json")
        history = json.loads(backup_path.read_text(encoding="utf-8")) if backup_path.exists() else []
        history.append(record)
        backup_path.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")
        log.info("로컬 백업 저장 완료 (posted_tweets.json)")


# ──────────────────────────────────────────────
# 금지어 필터
# ──────────────────────────────────────────────
BANNED_WORDS = [
    "매스프레소", "mathpresso",  # 회사 내부 이름
    "체크매스", "CheckMath",     # 경쟁사
    "포토매스", "PhotoMath",     # 경쟁사
    "바이럴", "광고",            # 광고 느낌 단어
]


def contains_banned_words(text: str) -> bool:
    text_lower = text.lower()
    for word in BANNED_WORDS:
        if word.lower() in text_lower:
            log.warning(f"금지어 감지: '{word}' in tweet")
            return True
    return False


# ──────────────────────────────────────────────
# 메인 파이프라인
# ──────────────────────────────────────────────
def main(dry_run: bool = False):
    log.info("=" * 50)
    log.info("🚀 공부법 트윗 자동생성 시작")
    log.info("=" * 50)

    # 환경변수 검증
    if not all([SUPABASE_URL, SUPABASE_KEY, ANTHROPIC_API_KEY]):
        log.error("필수 환경변수 누락: SUPABASE_URL, SUPABASE_KEY, ANTHROPIC_API_KEY")
        return

    # Supabase 클라이언트
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

    # 오늘 이미 포스팅된 수 확인
    today_count = get_today_post_count(supabase)
    if today_count >= MAX_TWEETS_PER_DAY:
        log.info(f"오늘 이미 {today_count}개 포스팅됨 (최대 {MAX_TWEETS_PER_DAY}개). 종료.")
        return

    # 콴다 언급 여부 결정
    total_count = get_total_post_count(supabase)
    include_qanda = (total_count % QANDA_MENTION_EVERY_N == QANDA_MENTION_EVERY_N - 1)
    log.info(f"콴다 언급: {'O' if include_qanda else 'X'} (전체 {total_count}번째 트윗)")

    # Step 1: 트렌드 가져오기
    trending = fetch_trending_tweets(supabase)
    if not trending:
        log.warning("수집된 트윗이 없습니다. 종료.")
        return

    # Step 1.5: Top 트윗의 스레드 가져오기
    top_tweet_ids = [t["tweet_id"] for t in trending[:5] if t.get("tweet_id")]
    threads = fetch_threads_for_tweets(supabase, top_tweet_ids)

    # 이전 생성 트윗 (중복 방지)
    previous = fetch_recent_generated(supabase)

    # Step 2: 트윗 생성 + AI 리뷰 (최대 5회 재시도)
    tweet_text = None
    for attempt in range(5):
        log.info(f"--- 시도 {attempt + 1}/5 ---")

        candidate = generate_tweet(trending, previous, include_qanda, threads)

        if contains_banned_words(candidate):
            log.warning(f"재시도: 금지어 포함")
            continue

        if is_too_similar(candidate, previous):
            log.warning(f"재시도: 기존 트윗과 유사")
            continue

        # AI 리뷰 (품질 검증)
        review = review_tweet(candidate)
        if not review.get("pass", False):
            log.warning(f"재시도: 리뷰 미통과")
            continue

        tweet_text = candidate
        break

    if not tweet_text:
        log.error("5회 시도 후에도 리뷰를 통과하는 트윗을 생성하지 못했습니다.")
        return

    # 결과 출력
    log.info(f"\n{'─' * 40}")
    log.info(f"📝 최종 트윗:")
    log.info(f"   {tweet_text}")
    log.info(f"   ({len(tweet_text)}자)")
    log.info(f"{'─' * 40}")

    # Step 2.5: 스레드 답글 생성
    log.info("🧵 스레드 답글 생성 중...")
    thread_replies = generate_thread_replies(tweet_text, include_qanda)
    if thread_replies:
        for i, r in enumerate(thread_replies, 1):
            log.info(f"   🧵 스레드 {i}: {r}")

    if dry_run:
        log.info("🧪 DRY RUN 모드 — 포스팅 건너뜀")
        return

    # Step 3: 메인 트윗 X API 포스팅
    tweet_id = post_to_x(tweet_text)

    # Step 3.5: 스레드 답글 포스팅
    if tweet_id and thread_replies:
        log.info("🧵 스레드 답글 포스팅 시작...")
        thread_ids = post_thread_to_x(tweet_id, thread_replies)
        log.info(f"🧵 스레드 {len(thread_ids)}개 포스팅 완료")

    # Step 4: 로그 저장
    save_generated_tweet(supabase, tweet_text, tweet_id, trending)

    log.info("✅ 파이프라인 완료!")


if __name__ == "__main__":
    import sys
    dry = "--dry-run" in sys.argv or "-d" in sys.argv
    if dry:
        print("🧪 DRY RUN 모드로 실행합니다 (포스팅 없이 생성만)")
    main(dry_run=dry)
