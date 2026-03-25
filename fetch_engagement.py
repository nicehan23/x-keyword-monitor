from __future__ import annotations

#!/usr/bin/env python3
"""
포스팅된 트윗의 인게이지먼트를 X API에서 가져와 Supabase에 업데이트.
"""

import os
import logging
from datetime import datetime, timezone

from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("engagement.log", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
X_BEARER_TOKEN = os.getenv("X_BEARER_TOKEN")


def fetch_engagement():
    import requests

    log.info("=" * 50)
    log.info("📊 인게이지먼트 수집 시작")
    log.info("=" * 50)

    if not all([SUPABASE_URL, SUPABASE_KEY, X_BEARER_TOKEN]):
        log.error("필수 환경변수 누락: SUPABASE_URL, SUPABASE_KEY, X_BEARER_TOKEN")
        return

    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

    response = (
        supabase.table("generated_tweets")
        .select("id, tweet_id")
        .eq("status", "posted")
        .not_.is_("tweet_id", "null")
        .execute()
    )

    tweets = response.data or []
    if not tweets:
        log.info("업데이트할 포스팅된 트윗이 없습니다.")
        return

    log.info(f"포스팅된 트윗 {len(tweets)}개 인게이지먼트 조회 시작")

    headers = {"Authorization": f"Bearer {X_BEARER_TOKEN}"}
    updated = 0
    failed = 0

    for i in range(0, len(tweets), 100):
        batch = tweets[i:i + 100]
        ids = ",".join(t["tweet_id"] for t in batch)
        url = f"https://api.x.com/2/tweets?ids={ids}&tweet.fields=public_metrics"

        try:
            resp = requests.get(url, headers=headers)
            if resp.status_code != 200:
                log.error(f"X API 오류 (HTTP {resp.status_code}): {resp.text[:200]}")
                failed += len(batch)
                continue

            data = resp.json()
            id_map = {t["tweet_id"]: t["id"] for t in batch}

            for tweet_data in data.get("data", []):
                tid = tweet_data["id"]
                metrics = tweet_data.get("public_metrics", {})
                db_id = id_map.get(tid)
                if not db_id:
                    continue

                try:
                    supabase.table("generated_tweets").update({
                        "like_count": metrics.get("like_count", 0),
                        "retweet_count": metrics.get("retweet_count", 0),
                        "reply_count": metrics.get("reply_count", 0),
                        "impression_count": metrics.get("impression_count", 0),
                        "quote_count": metrics.get("quote_count", 0),
                        "bookmark_count": metrics.get("bookmark_count", 0),
                        "engagement_updated_at": datetime.now(timezone.utc).isoformat(),
                    }).eq("id", db_id).execute()

                    updated += 1
                    log.info(f"  ✅ {tid}: ♥{metrics.get('like_count',0)} 🔁{metrics.get('retweet_count',0)} 👁{metrics.get('impression_count',0)}")

                except Exception as e:
                    log.error(f"  ❌ DB 업데이트 실패 ({tid}): {e}")
                    failed += 1

            for err in data.get("errors", []):
                log.warning(f"  ⚠️  트윗 조회 불가 ({err.get('resource_id','')}): {err.get('detail','')}")

        except Exception as e:
            log.error(f"배치 조회 실패: {e}")
            failed += len(batch)

    log.info(f"📊 인게이지먼트 수집 완료: {updated}개 업데이트, {failed}개 실패")


if __name__ == "__main__":
    fetch_engagement()
