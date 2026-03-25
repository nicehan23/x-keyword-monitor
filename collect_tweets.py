#!/usr/bin/env python3
"""
X 키워드 모니터 — 트윗 수집 스크립트 v2
X API v2 Recent Search → Supabase 저장
+ Top 5 인기 트윗의 스레드(대화) 수집
"""

import os
import sys
import json
from datetime import datetime, timezone, timedelta

import tweepy
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

BEARER_TOKEN = os.getenv("X_BEARER_TOKEN")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not all([BEARER_TOKEN, SUPABASE_URL, SUPABASE_KEY]):
    print("❌ .env 파일에 X_BEARER_TOKEN, SUPABASE_URL, SUPABASE_KEY를 모두 입력해주세요.")
    sys.exit(1)

x_client = tweepy.Client(bearer_token=BEARER_TOKEN, wait_on_rate_limit=True)
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

TOP_N_FOR_THREADS = 5


# ════════════════════════════════════════
# 키워드 관리
# ════════════════════════════════════════

def add_keyword(keyword: str):
    existing = supabase.table("keywords").select("*").eq("keyword", keyword).execute()
    if existing.data:
        supabase.table("keywords").update({"is_active": True}).eq("keyword", keyword).execute()
        print(f"✅ 키워드 '{keyword}' 다시 활성화됨")
    else:
        supabase.table("keywords").insert({"keyword": keyword, "is_active": True}).execute()
        print(f"✅ 키워드 '{keyword}' 추가됨")

def remove_keyword(keyword: str):
    supabase.table("keywords").update({"is_active": False}).eq("keyword", keyword).execute()
    print(f"🚫 키워드 '{keyword}' 비활성화됨")

def delete_keyword(keyword: str):
    result = supabase.table("tweets").delete().eq("keyword", keyword).execute()
    deleted = len(result.data) if result.data else 0
    supabase.table("keywords").delete().eq("keyword", keyword).execute()
    print(f"🗑️  키워드 '{keyword}' 삭제 완료 (트윗 {deleted}건 함께 삭제됨)")

def list_keywords():
    result = supabase.table("keywords").select("*").order("created_at").execute()
    if not result.data:
        print("📭 등록된 키워드가 없습니다.")
        print("   python collect_tweets.py add 공부팁")
        return
    print("\n📋 키워드 목록:")
    print("-" * 40)
    for kw in result.data:
        status = "🟢 활성" if kw["is_active"] else "🔴 비활성"
        print(f"  {status}  {kw['keyword']}")
    print("-" * 40)

def get_active_keywords():
    result = supabase.table("keywords").select("keyword").eq("is_active", True).execute()
    return [row["keyword"] for row in result.data]


# ════════════════════════════════════════
# 트윗 수집
# ════════════════════════════════════════

def collect_tweets_for_keyword(keyword: str):
    print(f"\n🔍 '{keyword}' 수집 시작...")

    last = (
        supabase.table("tweets")
        .select("created_at")
        .eq("keyword", keyword)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )

    if last.data:
        start_time = last.data[0]["created_at"]
    else:
        start_time = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()

    try:
        response = x_client.search_recent_tweets(
            query=f"{keyword} -is:retweet",
            max_results=100,
            start_time=start_time,
            tweet_fields=["created_at", "public_metrics", "lang", "author_id", "conversation_id"],
            user_fields=["username", "name", "profile_image_url"],
            expansions=["author_id"],
        )
    except tweepy.errors.TweepyException as e:
        print(f"  ⚠️ API 오류: {e}")
        return 0

    if not response.data:
        print(f"  📭 새 트윗 없음")
        return 0

    users = {}
    if response.includes and "users" in response.includes:
        for user in response.includes["users"]:
            users[user.id] = {
                "username": user.username,
                "name": user.name,
                "profile_image_url": user.profile_image_url,
            }

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

    result = supabase.table("tweets").upsert(rows, on_conflict="tweet_id").execute()
    count = len(result.data) if result.data else 0
    print(f"  ✅ {count}건 저장 완료")
    return count


# ════════════════════════════════════════
# 스레드 수집 (Top 5)
# ════════════════════════════════════════

def get_top_tweets(days=7, limit=TOP_N_FOR_THREADS):
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    result = (
        supabase.table("tweets")
        .select("tweet_id, author_username, text, keyword, like_count, retweet_count")
        .gte("created_at", cutoff)
        .order("retweet_count", desc=True)
        .limit(limit)
        .execute()
    )
    return result.data or []

def collect_thread(tweet_id, author_username, keyword):
    existing = (
        supabase.table("tweet_threads")
        .select("id", count="exact")
        .eq("parent_tweet_id", tweet_id)
        .execute()
    )
    if existing.count and existing.count > 0:
        return 0

    try:
        response = x_client.search_recent_tweets(
            query=f"conversation_id:{tweet_id} from:{author_username}",
            max_results=100,
            tweet_fields=["created_at", "author_id", "conversation_id", "in_reply_to_user_id"],
            user_fields=["username"],
            expansions=["author_id"],
        )
    except tweepy.errors.TweepyException as e:
        print(f"    ⚠️ 스레드 검색 오류: {e}")
        return 0

    if not response.data:
        return 0

    users = {}
    if response.includes and "users" in response.includes:
        for user in response.includes["users"]:
            users[user.id] = user.username

    thread_tweets = sorted(response.data, key=lambda t: t.created_at or datetime.min.replace(tzinfo=timezone.utc))

    collected_at = datetime.now(timezone.utc).isoformat()
    rows = []
    for position, tweet in enumerate(thread_tweets):
        rows.append({
            "parent_tweet_id": tweet_id,
            "tweet_id": str(tweet.id),
            "author_username": users.get(tweet.author_id, author_username),
            "text": tweet.text,
            "position": position + 1,
            "created_at": tweet.created_at.isoformat() if tweet.created_at else None,
            "collected_at": collected_at,
            "keyword": keyword,
        })

    if not rows:
        return 0

    result = supabase.table("tweet_threads").upsert(rows, on_conflict="tweet_id").execute()
    count = len(result.data) if result.data else 0
    return count

def collect_threads_for_top_tweets():
    print(f"\n🧵 Top {TOP_N_FOR_THREADS} 인기 트윗 스레드 수집 시작...")
    print("-" * 50)

    top_tweets = get_top_tweets()
    if not top_tweets:
        print("  📭 수집된 트윗이 없어 스레드 수집 건너뜀")
        return

    total_threads = 0
    for i, tweet in enumerate(top_tweets, 1):
        tweet_id = tweet["tweet_id"]
        author = tweet["author_username"]
        keyword = tweet.get("keyword", "")
        text_preview = tweet["text"][:50].replace("\n", " ")
        likes = tweet.get("like_count", 0)
        rts = tweet.get("retweet_count", 0)

        print(f"\n  #{i} @{author} (♥{likes} 🔁{rts})")
        print(f"     \"{text_preview}...\"")

        count = collect_thread(tweet_id, author, keyword)
        if count > 0:
            print(f"     🧵 스레드 {count}개 트윗 수집 완료")
            total_threads += count
        else:
            print(f"     — 스레드 없음 또는 이미 수집됨")

    print(f"\n{'─' * 50}")
    print(f"🧵 스레드 수집 완료! 총 {total_threads}건")


# ════════════════════════════════════════
# 전체 수집
# ════════════════════════════════════════

def collect_all():
    keywords = get_active_keywords()
    if not keywords:
        print("📭 활성 키워드가 없습니다.")
        print("   python collect_tweets.py add 공부팁")
        return

    print(f"🚀 수집 시작 — 활성 키워드 {len(keywords)}개: {', '.join(keywords)}")
    print("=" * 50)

    total = 0
    for kw in keywords:
        total += collect_tweets_for_keyword(kw)

    print("=" * 50)
    print(f"🎉 트윗 수집 완료! 총 {total}건 저장됨")

    # Top 5 스레드 수집
    collect_threads_for_top_tweets()

    print(f"\n⏰ 완료 시각: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")


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
    elif command == "threads":
        collect_threads_for_top_tweets()
    else:
        print("사용법:")
        print("  python collect_tweets.py            # 전체 키워드 수집 + 스레드")
        print("  python collect_tweets.py add 공부팁   # 키워드 추가")
        print("  python collect_tweets.py remove 공부팁 # 키워드 비활성화")
        print("  python collect_tweets.py delete 공부팁 # 키워드 + 트윗 완전 삭제")
        print("  python collect_tweets.py list        # 키워드 목록")
        print("  python collect_tweets.py threads     # Top 5 스레드만 수집")

if __name__ == "__main__":
    main()
