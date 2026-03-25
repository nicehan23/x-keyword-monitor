#!/bin/bash
set -e
echo ""
echo "╔══════════════════════════════════════════╗"
echo "║   트친소 자동 좋아요 + 맞팔로우 봇 설치   ║"
echo "╚══════════════════════════════════════════╝"
echo ""
echo "▶ [1/5] Python 확인 중..."
if command -v python3 &>/dev/null; then PY=python3
elif command -v python &>/dev/null; then PY=python
else echo "❌ Python이 없습니다. python.org에서 설치해주세요."; exit 1; fi
echo "  ✅ $($PY --version)"
echo ""
echo "▶ [2/5] 필요한 패키지 설치 중..."
$PY -m pip install --upgrade pip -q 2>/dev/null || true
$PY -m pip install requests requests-oauthlib -q
echo "  ✅ 패키지 설치 완료"
echo ""
echo "▶ [3/5] 봇 스크립트 생성 중..."
curl -sO https://raw.githubusercontent.com/mlt318/x-keyword-monitor/main/like_tchinso.py
echo "  ✅ like_tchinso.py 다운로드 완료"
echo ""
if [ -f .env ]; then
    echo "▶ [4/5] .env 파일이 이미 있습니다. 건너뜁니다."
else
    echo "▶ [4/5] X API 키를 입력해주세요."
    echo "  (https://developer.x.com/en/portal/dashboard 에서 확인)"
    echo ""
    read -p "  X_API_KEY: " api_key
    read -p "  X_API_SECRET: " api_secret
    read -p "  X_BEARER_TOKEN: " bearer_token
    read -p "  X_ACCESS_TOKEN: " access_token
    read -p "  X_ACCESS_TOKEN_SECRET: " access_token_secret
    cat > .env << EOF
X_API_KEY=${api_key}
X_API_SECRET=${api_secret}
X_BEARER_TOKEN=${bearer_token}
X_ACCESS_TOKEN=${access_token}
X_ACCESS_TOKEN_SECRET=${access_token_secret}
EOF
    echo ""
    echo "  ✅ .env 파일 생성 완료"
fi
echo ""
echo "▶ [5/5] 테스트 실행 (dry-run)..."
echo ""
$PY like_tchinso.py --dry-run
echo ""
echo "──────────────────────────────────────"
read -p "▶ 매일 아침 8시(KST) 자동 실행 등록할까요? (y/n): " setup_cron
if [ "$setup_cron" = "y" ] || [ "$setup_cron" = "Y" ]; then
    SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
    CRON_CMD="0 23 * * * cd ${SCRIPT_DIR} && ${PY} like_tchinso.py >> like_tchinso.log 2>&1"
    (crontab -l 2>/dev/null | grep -v "like_tchinso.py"; echo "$CRON_CMD") | crontab -
    echo "  ✅ cron 등록 완료! 매일 08:00 KST 자동 실행"
else
    echo "  ⏭ 건너뜀. 수동 실행: $PY like_tchinso.py"
fi
echo ""
echo "🎉 설치 완료!"
