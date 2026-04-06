#!/usr/bin/env python3
"""
X 키워드 모니터 — 트윗 수집 스크립트
X API v2 Recent Search → Supabase 저장
"""

import os
import sys
import json
from datetime import datetime, timezone, timedelta

import tweepy
from supabase import create_client, Client
from dotenv import load_dotenv

# ── 환경변수 로드 ──
load_dotenv()

BEARER_TOKEN = os.getenv("X_BEARER_TOKEN")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not all([BEARER_TOKEN, SUPABASE_URL, SUPABASE_KEY]):
    print("❌ .env 파일에 X_BEARER_TOKEN, SUPABASE_URL, SUPABASE_KEY를 모두 입력해주세요.")
    sys.exit(1)

# ── 클라이언트 초기화 ──
x_client = tweepy.Client(bearer_token=BEARER_TOKEN, wait_on_rate_limit=True)
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)


# ════════════════════════════════════════
# 키워드 관리
# ════════════════════════════════════════

def add_keyword(keyword: str):
    """키워드 추가 (이미 존재하면 활성화)"""
    existing = supabase.table("keywords").select("*").eq("keyword", keyword).execute()
    if existing.data:
        supabase.table("keywords").update({"is_active": True}).eq("keyword", keyword).execute()
        print(f"✅ 키워드 '{keyword}' 다시 활성화됨")
    else:
        supabase.table("keywords").insert({"keyword": keyword, "is_active": True}).execute()
        print(f"✅ 키워드 '{keyword}' 추가됨")


def remove_keyword(keyword: str):
    """키워드 비활성화"""
    supabase.table("keywords").update({"is_active": False}).eq("keyword", keyword).execute()
    print(f"🚫 키워드 '{keyword}' 비활성화됨")


def delete_keyword(keyword: str):
    """키워드 + 해당 트윗 데이터 완전 삭제"""
    # 트윗 먼저 삭제
    result = supabase.table("tweets").delete().eq("keyword", keyword).execute()
    deleted = len(result.data) if result.data else 0
    # 키워드 삭제
    supabase.table("keywords").delete().eq("keyword", keyword).execute()
    print(f"🗑️  키워드 '{keyword}' 삭제 완료 (트윗 {deleted}건 함께 삭제됨)")


def list_keywords():
    """키워드 목록 출력"""
    result = supabase.table("keywords").select("*").order("created_at").execute()
    if not result.data:
        print("📭 등록된 키워드가 없습니다. 먼저 키워드를 추가하세요:")
        print("   python collect_tweets.py add 공부팁")
        return
    print("\n📋 키워드 목록:")
    print("-" * 40)
    for kw in result.data:
        status = "🟢 활성" if kw["is_active"] else "🔴 비활성"
        print(f"  {status}  {kw['keyword']}")
    print("-" * 40)


def get_active_keywords() -> list[str]:
    """활성 키워드 목록 반환"""
    result = supabase.table("keywords").select("keyword").eq("is_active", True).execute()
    return [row["keyword"] for row in result.data]


# ════════════════════════════════════════
# 트윗 수집
# ════════════════════════════════════════

def collect_tweets_for_keyword(keyword: str):
    """특정 키워드로 최근 트윗 수집"""
    print(f"\n🔍 '{keyword}' 수집 시작...")

    # 최근 수집 시간 확인 (중복 방지)
    last = (
        supabase.table("tweets")
        .select("created_at")
        .eq("keyword", keyword)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )

    # 검색 시작 시간: 마지막 수집 이후 또는 7일 전
    if last.data:
        start_time = last.data[0]["created_at"]
    else:
        start_time = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()

    try:
        response = x_client.search_recent_tweets(
            query=f"{keyword} -is:retweet -from:qanda_zoe",
            max_results=100,
            start_time=start_time,
            tweet_fields=["created_at", "public_metrics", "lang", "author_id"],
            user_fields=["username", "name", "profile_image_url"],
            expansions=["author_id"],
        )
    except tweepy.errors.TweepyException as e:
        print(f"  ⚠️ API 오류: {e}")
        return 0

    if not response.data:
        print(f"  📭 새 트윗 없음")
        return 0

    # 사용자 정보 매핑
    users = {}
    if response.includes and "users" in response.includes:
        for user in response.includes["users"]:
            users[user.id] = {
                "username": user.username,
                "name": user.name,
                "profile_image_url": user.profile_image_url,
            }

    # Supabase에 저장
    collected_at = datetime.now(timezone.utc).isoformat()
    rows = []
    for tweet in response.data:
        metrics = tweet.public_metrics or {}
        author = users.get(tweet.author_id, {})
        rows.append({
            "tweet_id": str(tweet.id),
            "keyword": keyword,
            "author_username": author.get("username", ""),
            "author_name": author.get("name", ""),
            "author_profile_image": author.get("profile_image_url", ""),
            "text": tweet.text,
            "created_at": tweet.created_at.isoformat() if tweet.created_at else None,
            "like_count": metrics.get("like_count", 0),
            "retweet_count": metrics.get("retweet_count", 0),
            "reply_count": metrics.get("reply_count", 0),
            "impression_count": metrics.get("impression_count", 0),
            "lang": tweet.lang if hasattr(tweet, "lang") else None,
            "collected_at": collected_at,
        })

    # upsert로 중복 방지 (tweet_id 기준)
    result = supabase.table("tweets").upsert(rows, on_conflict="tweet_id").execute()
    count = len(result.data) if result.data else 0
    print(f"  ✅ {count}건 저장 완료")
    return count


def collect_all():
    """모든 활성 키워드에 대해 수집 실행"""
    keywords = get_active_keywords()
    if not keywords:
        print("📭 활성 키워드가 없습니다. 먼저 키워드를 추가하세요:")
        print("   python collect_tweets.py add 공부팁")
        return

    print(f"🚀 수집 시작 — 활성 키워드 {len(keywords)}개: {', '.join(keywords)}")
    print("=" * 50)

    total = 0
    for kw in keywords:
        total += collect_tweets_for_keyword(kw)

    print("=" * 50)
    print(f"🎉 수집 완료! 총 {total}건 저장됨")
    print(f"   시각: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")


# ════════════════════════════════════════
# CLI
# ════════════════════════════════════════

def main():
    if len(sys.argv) < 2:
        collect_all()
        return

    command = sys.argv[1].lower()

    if command == "add" and len(sys.argv) >= 3:
        add_keyword(sys.argv[2])
    elif command == "remove" and len(sys.argv) >= 3:
        remove_keyword(sys.argv[2])
    elif command == "delete" and len(sys.argv) >= 3:
        delete_keyword(sys.argv[2])
    elif command == "list":
        list_keywords()
    else:
        print("사용법:")
        print("  python collect_tweets.py            # 전체 키워드 수집")
        print("  python collect_tweets.py add 공부팁   # 키워드 추가")
        print("  python collect_tweets.py remove 공부팁 # 키워드 비활성화")
        print("  python collect_tweets.py delete 공부팁 # 키워드 + 트윗 완전 삭제")
        print("  python collect_tweets.py list        # 키워드 목록")


if __name__ == "__main__":
    main()
