#!/bin/bash
set -e
echo ""
echo "=================================================="
echo "  🚀 공부법 트윗 자동생성 시스템 설치를 시작합니다"
echo "=================================================="
echo ""
INSTALL_DIR="$HOME/x-keyword-monitor"
if [ -d "$INSTALL_DIR" ]; then
    echo "📁 이미 $INSTALL_DIR 폴더가 존재합니다. 업데이트합니다."
else
    echo "📁 프로젝트 폴더를 생성합니다: $INSTALL_DIR"
    mkdir -p "$INSTALL_DIR"
fi
cd "$INSTALL_DIR"
echo "✅ 프로젝트 폴더 준비 완료"
echo ""
echo "🐍 Python 확인 중..."
if command -v python3 &> /dev/null; then
    echo "✅ $(python3 --version 2>&1) 확인됨"
else
    echo "❌ Python3가 설치되어 있지 않습니다."
    echo "   brew install python3 실행 후 다시 시도하세요."
    exit 1
fi
echo ""
echo "📦 필요한 패키지를 설치합니다..."
pip3 install --break-system-packages --quiet anthropic supabase python-dotenv tweepy requests 2>/dev/null || pip3 install anthropic supabase python-dotenv tweepy requests
echo "✅ 패키지 설치 완료"
echo ""
echo "📥 최신 코드를 다운로드합니다..."
REPO_URL="https://raw.githubusercontent.com/nicehan23/x-keyword-monitor/main"
for file in collect_tweets.py generate_and_post.py tweet_templates.py fetch_engagement.py tweet-dashboard.html; do
    echo "   다운로드: $file"
    curl -sL "$REPO_URL/$file" -o "$INSTALL_DIR/$file"
done
echo "✅ 코드 다운로드 완료"
echo ""
if [ -f "$INSTALL_DIR/.env" ]; then
    echo "⚙️  .env 파일이 이미 존재합니다."
    read -p "   API 키를 다시 설정하시겠습니까? (y/N): " RESET_ENV
    if [ "$RESET_ENV" != "y" ] && [ "$RESET_ENV" != "Y" ]; then
        SKIP_ENV=true
    fi
fi
if [ "$SKIP_ENV" != "true" ]; then
    echo ""
    echo "=================================================="
    echo "  🔑 API 키 설정"
    echo "=================================================="
    echo ""
    echo "X Developer Portal에서 발급받은 키를 입력해주세요."
    echo ""
    read -p "X_BEARER_TOKEN: " X_BEARER_TOKEN
    read -p "X_API_KEY (Consumer Key): " X_API_KEY
    read -p "X_API_SECRET (Consumer Secret): " X_API_SECRET
    read -p "X_ACCESS_TOKEN: " X_ACCESS_TOKEN
    read -p "X_ACCESS_TOKEN_SECRET: " X_ACCESS_TOKEN_SECRET
    echo ""
    read -p "ANTHROPIC_API_KEY (Claude API): " ANTHROPIC_API_KEY
    echo ""
    cat > "$INSTALL_DIR/.env" << ENVEOF
X_BEARER_TOKEN=$X_BEARER_TOKEN
X_API_KEY=$X_API_KEY
X_API_SECRET=$X_API_SECRET
X_ACCESS_TOKEN=$X_ACCESS_TOKEN
X_ACCESS_TOKEN_SECRET=$X_ACCESS_TOKEN_SECRET
ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY
SUPABASE_URL=https://nuauodpvylurlynlwcfy.supabase.co
SUPABASE_KEY=sb_publishable_A-2qRZZRzB5p-ClUDGygzQ_KX6wAykW
ENVEOF
    echo "✅ .env 파일 생성 완료"
fi
echo ""
echo "🔧 Python 호환성 패치 적용 중..."
for pyfile in generate_and_post.py fetch_engagement.py; do
    if [ -f "$INSTALL_DIR/$pyfile" ]; then
        if ! head -1 "$INSTALL_DIR/$pyfile" | grep -q "from __future__"; then
            sed -i '' '1s/^/from __future__ import annotations\n/' "$INSTALL_DIR/$pyfile" 2>/dev/null || sed -i '1s/^/from __future__ import annotations\n/' "$INSTALL_DIR/$pyfile"
        fi
    fi
done
echo "✅ 호환성 패치 완료"
echo ""
echo "⏰ 자동 실행 스케줄을 등록합니다..."
PYTHON_PATH=$(which python3)
(crontab -l 2>/dev/null | grep -v "x-keyword-monitor") | crontab -
(crontab -l 2>/dev/null
echo "0 23 * * * cd $INSTALL_DIR && $PYTHON_PATH collect_tweets.py >> cron.log 2>&1"
echo "30 7 * * * cd $INSTALL_DIR && $PYTHON_PATH fetch_engagement.py >> engagement_cron.log 2>&1"
echo "0 8 * * * cd $INSTALL_DIR && $PYTHON_PATH generate_and_post.py >> cron.log 2>&1"
echo "0 17 * * * cd $INSTALL_DIR && $PYTHON_PATH generate_and_post.py >> cron.log 2>&1"
echo "0 18 * * * cd $INSTALL_DIR && $PYTHON_PATH generate_and_post.py >> cron.log 2>&1"
echo "0 20 * * * cd $INSTALL_DIR && $PYTHON_PATH generate_and_post.py >> cron.log 2>&1"
) | crontab -
echo "✅ 스케줄 등록 완료"
echo ""
echo "🧪 테스트 실행..."
echo ""
cd "$INSTALL_DIR"
$PYTHON_PATH generate_and_post.py --dry-run
echo ""
echo "=================================================="
echo "  ✅ 설치 완료!"
echo "=================================================="
echo ""
echo "📊 대시보드: file://$INSTALL_DIR/tweet-dashboard.html"
echo "📌 즉시 포스팅: cd $INSTALL_DIR && python3 generate_and_post.py"
echo "📌 스케줄 확인: crontab -l"
echo ""
