#!/usr/bin/env python3
"""
한국 공부 관련 X 인플루언서 추가 검색 (2차)
기존에 찾은 계정 제외, 새 키워드 조합
"""

import os
import json
from collections import defaultdict
from dotenv import load_dotenv
import tweepy

load_dotenv()

BEARER_TOKEN = os.getenv("X_BEARER_TOKEN")
client = tweepy.Client(bearer_token=BEARER_TOKEN, wait_on_rate_limit=True)

# 이미 찾은 계정 제외
ALREADY_FOUND = {
    "Bansoogogo", "admi_alts", "sujaaaaaaaa_26", "cherryplan2",
    "whyblueloves", "in3seconds", "stelo_kim", "yu_yeong23",
    "zagi_94", "Tomato56981612",
}

# 2차 키워드 — 더 구체적인 공부 관련 키워드
KEYWORDS = [
    "공부 타임랩스", "공스타그램", "스터디윗미",
    "공부 브이로그", "공부 동기부여", "합격 후기",
    "공부 플래너", "공부 꿀팁", "시험 준비",
    "의대 공부", "로스쿨", "편입 준비",
    "코딩 공부", "영어 공부법", "일본어 공부",
    "독서 기록", "책 추천", "필사",
]

def search_influencers(min_followers=2000):
    authors = {}

    for keyword in KEYWORDS:
        query = f"{keyword} lang:ko -is:retweet"
        print(f"🔍 검색 중: {keyword}")

        try:
            response = client.search_recent_tweets(
                query=query,
                max_results=100,
                tweet_fields=["public_metrics", "author_id", "created_at"],
                user_fields=["public_metrics", "description", "name", "username"],
                expansions=["author_id"],
            )
        except tweepy.errors.TweepyException as e:
            print(f"  ⚠️ 오류: {e}")
            continue

        if not response.data or not response.includes:
            print(f"  📭 결과 없음")
            continue

        users = response.includes.get("users", [])
        tweet_authors = defaultdict(lambda: {"tweets": 0, "total_likes": 0, "total_rts": 0})
        for tweet in response.data:
            m = tweet.public_metrics or {}
            aid = tweet.author_id
            tweet_authors[aid]["tweets"] += 1
            tweet_authors[aid]["total_likes"] += m.get("like_count", 0)
            tweet_authors[aid]["total_rts"] += m.get("retweet_count", 0)

        for user in users:
            uid = user.id
            if user.username in ALREADY_FOUND:
                continue

            followers = user.public_metrics.get("followers_count", 0) if user.public_metrics else 0

            if uid not in authors:
                authors[uid] = {
                    "username": user.username,
                    "name": user.name,
                    "followers": followers,
                    "description": user.description or "",
                    "keywords": set(),
                    "total_tweets": 0,
                    "total_likes": 0,
                    "total_rts": 0,
                }

            authors[uid]["keywords"].add(keyword)
            stats = tweet_authors.get(uid, {})
            authors[uid]["total_tweets"] += stats.get("tweets", 0)
            authors[uid]["total_likes"] += stats.get("total_likes", 0)
            authors[uid]["total_rts"] += stats.get("total_rts", 0)

        print(f"  ✅ 유저 {len(users)}명 발견")

    influencers = [
        v for v in authors.values()
        if v["followers"] >= min_followers
    ]
    influencers.sort(key=lambda x: x["followers"], reverse=True)

    for inf in influencers:
        inf["keywords"] = list(inf["keywords"])

    return influencers


if __name__ == "__main__":
    print("🚀 2차 공부 인플루언서 검색 시작\n")
    results = search_influencers(min_followers=2000)

    print(f"\n{'='*60}")
    print(f"📊 팔로워 2,000명 이상 인플루언서: {len(results)}명\n")

    for i, inf in enumerate(results, 1):
        print(f"  {i:3d}. @{inf['username']} ({inf['name']})")
        print(f"       팔로워: {inf['followers']:,} | 트윗: {inf['total_tweets']} | ♥ {inf['total_likes']:,}")
        print(f"       키워드: {', '.join(inf['keywords'])}")
        print(f"       소개: {inf['description'][:80]}")
        print()

    output_path = os.path.join(os.path.dirname(__file__), "influencers_result2.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"💾 결과 저장: {output_path}")
