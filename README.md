# Personal Milestone

微信小程序后端（FastAPI）：Goal → Milestone → Task，AI WBS + 日安排（**当前 `LLM_MODE=mock`，不请求 DeepSeek**）。

规格见 `docs/sdd/`。

## 环境区分

| | `dev`（本地） | `live`（线上） |
|--|-------|--------|
| 应用配置 | `config/dev.yaml` | `config/live.yaml`（由 `live.yaml.example` 复制） |
| Compose | `docker-compose.yml` + `docker-compose.dev.yml` | `docker-compose.yml` + `docker-compose.live.yml` |
| 数据库 | MySQL 8.4（开发口令） | MySQL 8.0 容器 `personal_db` |
| 微信登录 | `wechat_mock: true` | 禁止 mock |
| Secrets | 可用占位值 | 启动时校验，弱密钥会拒绝启动 |
| `/docs` | 默认开 | 默认关 |

加载顺序（后者可被前者覆盖）：进程环境变量 > `config/{APP_ENV}.yaml`。  
`APP_ENV` 取 `dev` 或 `live`（`prod` / `production` 会归一为 `live`）。

## 快速开始（dev）

```bash
cd /Users/fuzhe/personal_milestone

# 1) 本地 MySQL（需 Docker Desktop；若 brew MySQL 占 3306：brew services stop mysql）
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
APP_ENV=dev alembic upgrade head
APP_ENV=dev uvicorn main:app --reload --port 8000
```

- 健康检查：`GET http://127.0.0.1:8000/health`（含 `app_env`）
- OpenAPI：`http://127.0.0.1:8000/docs`
- 微信登录：任意 `code` 即可签发 JWT
- 默认连接见 `config/dev.yaml` → `database_url`
- 表结构由 Alembic 管理（`alembic/versions/`），**不要**再依赖启动时 `create_all`

### Compose 命令

```bash
# 本地
alias dc-dev='docker compose -f docker-compose.yml -f docker-compose.dev.yml'
dc-dev up -d          # 启动
dc-dev ps             # 状态
dc-dev logs -f mysql  # 日志
dc-dev down           # 停止（保留数据卷）

# 线上
alias dc-live='docker compose -f docker-compose.yml -f docker-compose.live.yml'
dc-live up -d
```

| | 本地 `dev` | 线上 `live` |
|--|------------|-------------|
| 项目名 | `personal_milestone_dev` | `personal_milestone_live` |
| 镜像 | `mysql:8.4`（DaoCloud） | `mysql:8.0` |
| 容器名 | `personal_milestone_mysql_dev` | `personal_db` |
| 端口 | `3306:3306` | `3306:3306` |
| root 密码 | `root` | 启动前 `export MYSQL_ROOT_PASSWORD=...` |
| 数据卷 | `mysql_data` | `mysql_data` |
| restart | `unless-stopped` | `always` |

## 线上（live）

已有 `personal_db` 时：填好 `config/live.yaml`，再编辑 `scripts/start_live.sh` 里的密码后执行：

```bash
bash scripts/start_live.sh
```

脚本内会执行 `APP_ENV=live alembic upgrade head` 再建表并启动。

## 数据库迁移（Alembic）

```bash
# 应用迁移到最新
APP_ENV=dev alembic upgrade head

# 改模型后生成新迁移
APP_ENV=dev alembic revision --autogenerate -m "add_xxx"

# 查看当前版本
APP_ENV=dev alembic current
```

若库里表已由旧版 `create_all` 建好、只需登记版本：

```bash
APP_ENV=dev alembic stamp head
```

## 冒烟流程

```bash
source .venv/bin/activate
APP_ENV=dev python scripts/smoke_test.py
```

典型 API 顺序：

1. `POST /api/v1/auth/wechat/login` `{ "code": "dev" }`
2. `POST /api/v1/goals` → 202 + `job_id`（mock 同步写入 suggested WBS）
3. `GET /api/v1/jobs/{job_id}` → `result_ref.generation_id`
4. `POST .../wbs/generations/{id}/confirm`
5. `GET /api/v1/home` / `GET /api/v1/gantt`
6. `POST .../today-tasks/{task_id}/complete|incomplete`
7. 日终：`POST /internal/jobs/day-close/run` + 头 `X-Internal-Token`

## 配置项（`config/{dev,live}.yaml`）

| 键 | dev 典型值 | live 要求 |
|------|------------|-----------|
| `app_env` | `dev` | `live` |
| `database_url` | `mysql+pymysql://root:root@127.0.0.1:3306/personal_milestone` | MySQL，禁止 SQLite |
| `llm_mode` | `mock` | 首期可 `mock`；接模型后 `deepseek` |
| `wechat_mock` | `true` | 必须 `false` |
| `jwt_secret` | 占位即可 | ≥16 且非占位 |
| `internal_token` | 占位即可 | ≥16 且非占位 |
| `enable_docs` | `true` | 建议 `false` |
| `jwt_expire_seconds` | `7200` | 按需 |
