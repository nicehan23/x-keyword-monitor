#!/usr/bin/env python3
"""
트친소 자동 좋아요 + 맞팔로우 봇
=================================
#공부계_트친소 / #공부계트친소 해시태그의 신규 트윗에 좋아요를 자동으로 누르고,
좋아요를 누른 유저 중 나를 팔로우한 사람에게 맞팔로우를 한다.
X 공식 API v2를 사용하여 정지 위험을 최소화한다.

사용법:
  python like_tchinso.py                # 좋아요 + 맞팔로우 실행
  python like_tchinso.py --dry-run      # 검색만 하고 실행하지 않음
  python like_tchinso.py --like-only    # 좋아요만 실행 (맞팔로우 안 함)
  python like_tchinso.py --follow-only  # 맞팔로우만 실행 (좋아요 안 함)
"""
from __future__ import annotations

import json
import os
import sys
import time
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests
from requests_oauthlib import OAuth1

# ── 설정 ──────────────────────────────────────────────
HASHTAGS = ["#공부계_트친소", "#공부계트친소"]
MAX_LIKES_PER_RUN = 50          # 하루 최대 좋아요 개수
MAX_FOLLOWS_PER_RUN = 15        # 하루 최대 맞팔로우 개수 (보수적으로)
LIKED_LOG_FILE = Path(__file__).parent / ".liked_tchinso.json"
LOG_RETENTION_DAYS = 7          # 로그 보관 기간 (일)

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("like_tchinso")


# ── 환경변수 로드 ─────────────────────────────────────
def load_env() -> None:
    """같은 폴더 또는 ~/x-keyword-monitor/.env 에서 환경변수를 읽는다."""
    env_paths = [
        Path(__file__).parent / ".env",
        Path.home() / "x-keyword-monitor" / ".env",
    ]
    for env_path in env_paths:
        if env_path.exists():
            log.info(f".env 로드: {env_path}")
            with open(env_path) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        key, _, value = line.partition("=")
                        os.environ.setdefault(key.strip(), value.strip())
            return
    log.warning(".env 파일을 찾을 수 없습니다. 환경변수가 이미 설정되어 있어야 합니다.")


def get_env(key: str) -> str:
    val = os.environ.get(key)
    if not val:
        log.error(f"환경변수 {key}가 설정되지 않았습니다.")
        sys.exit(1)
    return val


# ── X API 인증 ────────────────────────────────────────
def get_oauth1() -> OAuth1:
    return OAuth1(
        get_env("X_API_KEY"),
        get_env("X_API_SECRET"),
        get_env("X_ACCESS_TOKEN"),
        get_env("X_ACCESS_TOKEN_SECRET"),
    )


def get_bearer_header() -> dict:
    return {"Authorization": f"Bearer {get_env('X_BEARER_TOKEN')}"}


def get_my_user_id() -> str:
    url = "https://api.twitter.com/2/users/me"
    resp = requests.get(url, auth=get_oauth1(), timeout=10)
    resp.raise_for_status()
    user_id = resp.json()["data"]["id"]
    log.info(f"내 사용자 ID: {user_id}")
    return user_id


# ── 좋아요 기록 관리 (로컬 JSON) ─────────────────────
def load_liked_ids() -> set:
    if not LIKED_LOG_FILE.exists():
        return set()
    try:
        with open(LIKED_LOG_FILE) as f:
            data = json.load(f)
        cutoff = (datetime.now(timezone.utc) - timedelta(days=LOG_RETENTION_DAYS)).isoformat()
        cleaned = {tid: ts for tid, ts in data.items() if ts >= cutoff}
        return set(cleaned.keys())
    except (json.JSONDecodeError, TypeError):
        return set()


def save_liked_ids(liked_map: dict) -> None:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=LOG_RETENTION_DAYS)).isoformat()
    cleaned = {tid: ts for tid, ts in liked_map.items() if ts >= cutoff}
    with open(LIKED_LOG_FILE, "w") as f:
        json.dump(cleaned, f, indent=2)


def load_liked_map() -> dict:
    if not LIKED_LOG_FILE.exists():
        return {}
    try:
        with open(LIKED_LOG_FILE) as f:
            return json.load(f)
    except (json.JSONDecodeError, TypeError):
        return {}


# ── 해시태그 검색 ─────────────────────────────────────
def search_tweets(hashtag: str, max_results: int = 50) -> list[dict]:
    url = "https://api.twitter.com/2/tweets/search/recent"
    since = (datetime.now(timezone.utc) - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%SZ")

    params = {
        "query": f"{hashtag} -is:retweet",
        "max_results": min(max_results, 100),
        "start_time": since,
        "tweet.fields": "author_id,created_at,public_metrics",
    }

    resp = requests.get(url, headers=get_bearer_header(), params=params, timeout=15)

    if resp.status_code == 429:
        reset = resp.headers.get("x-rate-limit-reset")
        wait = int(reset) - int(time.time()) if reset else 60
        log.warning(f"Rate limit! {wait}초 후 재시도...")
        time.sleep(max(wait + 1, 1))
        resp = requests.get(url, headers=get_bearer_header(), params=params, timeout=15)

    if resp.status_code != 200:
        log.error(f"검색 실패 [{resp.status_code}]: {resp.text}")
        return []

    data = resp.json()
    tweets = data.get("data", [])
    count = data.get("meta", {}).get("result_count", 0)
    log.info(f"'{hashtag}' 검색 결과: {count}개")
    return tweets


# ── 좋아요 실행 ───────────────────────────────────────
def like_tweet(user_id: str, tweet_id: str) -> bool:
    url = f"https://api.twitter.com/2/users/{user_id}/likes"
    payload = {"tweet_id": tweet_id}

    resp = requests.post(url, auth=get_oauth1(), json=payload, timeout=10)

    if resp.status_code == 200:
        liked = resp.json().get("data", {}).get("liked", False)
        if liked:
            log.info(f"  ✓ 좋아요 성공: {tweet_id}")
            return True
        else:
            log.info(f"  - 이미 좋아요됨: {tweet_id}")
            return True
    elif resp.status_code == 429:
        log.warning("  ✗ Rate limit 도달. 중단합니다.")
        return False
    else:
        log.error(f"  ✗ 좋아요 실패 [{resp.status_code}]: {resp.text}")
        return False


# ── 맞팔로우 기능 ─────────────────────────────────────
def get_followers(user_id: str) -> set:
    url = f"https://api.twitter.com/2/users/{user_id}/followers"
    followers = set()
    params = {"max_results": 1000}

    while True:
        resp = requests.get(url, auth=get_oauth1(), params=params, timeout=15)
        if resp.status_code == 429:
            reset = resp.headers.get("x-rate-limit-reset")
            wait = int(reset) - int(time.time()) if reset else 60
            log.warning(f"Rate limit (followers)! {wait}초 후 재시도...")
            time.sleep(max(wait + 1, 1))
            resp = requests.get(url, auth=get_oauth1(), params=params, timeout=15)

        if resp.status_code != 200:
            log.error(f"팔로워 조회 실패 [{resp.status_code}]: {resp.text}")
            break

        data = resp.json()
        for user in data.get("data", []):
            followers.add(user["id"])

        next_token = data.get("meta", {}).get("next_token")
        if next_token:
            params["pagination_token"] = next_token
        else:
            break
        time.sleep(1)

    log.info(f"내 팔로워: {len(followers)}명")
    return followers


def get_following(user_id: str) -> set:
    url = f"https://api.twitter.com/2/users/{user_id}/following"
    following = set()
    params = {"max_results": 1000}

    while True:
        resp = requests.get(url, auth=get_oauth1(), params=params, timeout=15)
        if resp.status_code == 429:
            reset = resp.headers.get("x-rate-limit-reset")
            wait = int(reset) - int(time.time()) if reset else 60
            log.warning(f"Rate limit (following)! {wait}초 후 재시도...")
            time.sleep(max(wait + 1, 1))
            resp = requests.get(url, auth=get_oauth1(), params=params, timeout=15)

        if resp.status_code != 200:
            log.error(f"팔로잉 조회 실패 [{resp.status_code}]: {resp.text}")
            break

        data = resp.json()
        for user in data.get("data", []):
            following.add(user["id"])

        next_token = data.get("meta", {}).get("next_token")
        if next_token:
            params["pagination_token"] = next_token
        else:
            break
        time.sleep(1)

    log.info(f"내 팔로잉: {len(following)}명")
    return following


def follow_user(my_user_id: str, target_user_id: str) -> bool:
    url = f"https://api.twitter.com/2/users/{my_user_id}/following"
    payload = {"target_user_id": target_user_id}

    resp = requests.post(url, auth=get_oauth1(), json=payload, timeout=10)

    if resp.status_code == 200:
        following = resp.json().get("data", {}).get("following", False)
        if following:
            log.info(f"  ✓ 맞팔로우 성공: {target_user_id}")
            return True
        else:
            pending = resp.json().get("data", {}).get("pending_follow", False)
            if pending:
                log.info(f"  ⏳ 팔로우 요청 보냄 (비공개 계정): {target_user_id}")
                return True
            log.info(f"  - 이미 팔로우 중: {target_user_id}")
            return True
    elif resp.status_code == 429:
        log.warning("  ✗ Rate limit 도달 (follow). 중단합니다.")
        return False
    else:
        log.error(f"  ✗ 팔로우 실패 [{resp.status_code}]: {resp.text}")
        return False


def do_follow_back(user_id: str, liked_author_ids: set, dry_run: bool = False) -> int:
    log.info("\n" + "=" * 50)
    log.info("맞팔로우 체크 시작")
    log.info(f"좋아요 누른 유저: {len(liked_author_ids)}명")
    log.info("=" * 50)

    if not liked_author_ids:
        log.info("좋아요 누른 유저가 없어 맞팔로우 건너뜀.")
        return 0

    my_followers = get_followers(user_id)
    my_following = get_following(user_id)

    follow_targets = liked_author_ids & my_followers - my_following
    log.info(f"맞팔로우 대상: {len(follow_targets)}명 "
             f"(좋아요 유저 중 팔로워이면서 내가 미팔로우)")

    if not follow_targets:
        log.info("맞팔로우할 대상이 없습니다.")
        return 0

    targets_list = list(follow_targets)[:MAX_FOLLOWS_PER_RUN]

    if dry_run:
        log.info(f"\n[DRY RUN] 맞팔로우 대상 {len(targets_list)}명:")
        for uid in targets_list:
            log.info(f"  - user_id: {uid}")
        return 0

    follow_count = 0
    for target_id in targets_list:
        success = follow_user(user_id, target_id)
        if success:
            follow_count += 1
        else:
            break
        time.sleep(2)

    log.info(f"맞팔로우 완료: {follow_count}/{len(targets_list)}명")
    return follow_count


# ── 메인 실행 ─────────────────────────────────────────
def main() -> None:
    dry_run = "--dry-run" in sys.argv
    like_only = "--like-only" in sys.argv
    follow_only = "--follow-only" in sys.argv

    do_like = not follow_only
    do_follow = not like_only

    load_env()
    log.info("=" * 50)
    mode_str = "DRY RUN" if dry_run else "LIVE"
    features = []
    if do_like:
        features.append("좋아요")
    if do_follow:
        features.append("맞팔로우")
    log.info(f"트친소 봇 시작 ({mode_str}) — {' + '.join(features)}")
    log.info(f"해시태그: {', '.join(HASHTAGS)}")
    log.info("=" * 50)

    user_id = None
    liked_author_ids = set()

    # ── STEP 1: 좋아요 ──
    if do_like:
        liked_map = load_liked_map()
        already_liked = set(liked_map.keys())
        log.info(f"기존 좋아요 기록: {len(already_liked)}개")

        all_tweets = []
        seen_ids = set()
        for tag in HASHTAGS:
            tweets = search_tweets(tag)
            for t in tweets:
                tid = t["id"]
                if tid not in seen_ids:
                    seen_ids.add(tid)
                    all_tweets.append(t)
            time.sleep(1)

        new_tweets = [t for t in all_tweets if t["id"] not in already_liked]
        log.info(f"전체 수집: {len(all_tweets)}개 → 신규: {len(new_tweets)}개")

        if new_tweets:
            target_tweets = new_tweets[:MAX_LIKES_PER_RUN]
            log.info(f"좋아요 대상: {len(target_tweets)}개")

            if dry_run:
                log.info("\n[DRY RUN] 좋아요 대상 트윗:\n")
                for i, t in enumerate(target_tweets, 1):
                    text_preview = t.get("text", "")[:80].replace("\n", " ")
                    metrics = t.get("public_metrics", {})
                    log.info(f"  {i}. [{t['id']}] {text_preview}...")
                    log.info(f"     ❤️ {metrics.get('like_count', 0)}  🔁 {metrics.get('retweet_count', 0)}")
                liked_author_ids = {t["author_id"] for t in target_tweets if "author_id" in t}
            else:
                user_id = get_my_user_id()
                success_count = 0
                for t in target_tweets:
                    tweet_id = t["id"]
                    success = like_tweet(user_id, tweet_id)
                    if success:
                        success_count += 1
                        liked_map[tweet_id] = datetime.now(timezone.utc).isoformat()
                        if "author_id" in t:
                            liked_author_ids.add(t["author_id"])
                    else:
                        log.warning("좋아요 중단됨.")
                        break
                    time.sleep(2)

                save_liked_ids(liked_map)
                log.info(f"\n좋아요 완료! {success_count}/{len(target_tweets)}개 성공")
        else:
            log.info("새로운 트윗이 없습니다.")
            liked_author_ids = {t["author_id"] for t in all_tweets if "author_id" in t}

    # ── STEP 2: 맞팔로우 ──
    if do_follow:
        if user_id is None and not dry_run:
            user_id = get_my_user_id()

        if follow_only:
            log.info("팔로우 전용 모드: 해시태그 트윗 작성자 수집 중...")
            for tag in HASHTAGS:
                tweets = search_tweets(tag, max_results=100)
                for t in tweets:
                    if "author_id" in t:
                        liked_author_ids.add(t["author_id"])
                time.sleep(1)

        if dry_run:
            user_id = user_id or get_my_user_id()

        do_follow_back(user_id, liked_author_ids, dry_run=dry_run)

    log.info("\n🎉 모든 작업 완료!")


if __name__ == "__main__":
    main()
