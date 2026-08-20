#!/usr/bin/env bash
# 线上启动（已有 personal_db 容器，或用 compose live 起 mysql/rabbitmq/worker/beat）
# 把下面空着的地方填好后执行：bash scripts/start_live.sh

set -euo pipefail
cd "$(dirname "$0")/.."

# ====== 请填写 ======
MYSQL_ROOT_PASSWORD=""
DB_NAME="personal_milestone"
MYSQL_CONTAINER="personal_db"
APP_PORT="8000"
# ====================

[[ -n "$MYSQL_ROOT_PASSWORD" ]] || { echo "请先填写 MYSQL_ROOT_PASSWORD"; exit 1; }
[[ -f config/live.yaml ]] || { echo "请先准备 config/live.yaml"; exit 1; }

docker exec "$MYSQL_CONTAINER" mysql -uroot -p"$MYSQL_ROOT_PASSWORD" \
  -e "CREATE DATABASE IF NOT EXISTS \`$DB_NAME\` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"

python3 -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate
pip install -r requirements.txt

APP_ENV=live alembic upgrade head

# 推荐：compose 起 RabbitMQ + worker + beat（与 uvicorn 分离）
#   export MYSQL_ROOT_PASSWORD=...
#   docker compose -f docker-compose.yml -f docker-compose.live.yml up -d rabbitmq worker beat

echo "Starting uvicorn on :$APP_PORT (ensure Celery worker/beat are running)"
APP_ENV=live uvicorn main:app --host 0.0.0.0 --port "$APP_PORT"
