# DSM 镜像部署指南

## 适用范围

本文只覆盖首次把 DSM 生产环境从旧的本地构建项目迁移到 `finance-reconciliation` 的 3 服务镜像部署：

- `db`
- `web`
- `updater`

示例使用 `http://sd.ace-station.top:1111` 代表既有外部入口。迁移不改变现场的协议、端口或转发目标。

## 预设环境变量

目标路径与运行时固定契约一致；旧路径、旧数据库 identity、备份目录、口令和 Token 只通过现场变量提供：

```bash
export FINREC_BASE_URL="http://sd.ace-station.top:1111"
export FINREC_APP_DIR="/volume4/docker/docker/finance-reconciliation/app"
export FINREC_DATA_DIR="/volume4/docker/docker/finance-reconciliation/data"
export FINREC_LEGACY_APP_DIR="<legacy-app-dir>"
export FINREC_LEGACY_DATA_DIR="<legacy-data-dir>"
export FINREC_LEGACY_COMPOSE_PROJECT="<legacy-compose-project>"
export FINREC_LEGACY_DATABASE_NAME="<legacy-database-name>"
export FINREC_LEGACY_DATABASE_ROLE="<legacy-database-role>"
export FINREC_BACKUP_ROOT="<backup-root>"
export FINREC_WEB_IMAGE_TAG="v0.2.0"
export FINREC_UPDATER_IMAGE_TAG="v0.2.0"
export FINREC_UPDATER_TOKEN="<32-byte-random-token>"
export FINREC_DEPLOY_MODE="identity-migration"
```

`FINREC_WEB_IMAGE_TAG` 和 `FINREC_UPDATER_IMAGE_TAG` 必须使用规范 `vX.Y.Z`。`FINREC_UPDATER_TOKEN` 必须至少 32 字节，并只保存在 DSM 的 `.env` 中。

## 先验证公开镜像可匿名拉取

在执行首个镜像部署前，先验证两个公开镜像都已经发布，并且匿名环境也能拉取：

```bash
export FINREC_EMPTY_DOCKER_CONFIG="$(mktemp -d)"
DOCKER_CONFIG="$FINREC_EMPTY_DOCKER_CONFIG" docker pull "ghcr.io/s450586793/finance-reconciliation-web:${FINREC_WEB_IMAGE_TAG}"
DOCKER_CONFIG="$FINREC_EMPTY_DOCKER_CONFIG" docker pull "ghcr.io/s450586793/finance-reconciliation-updater:${FINREC_UPDATER_IMAGE_TAG}"
```

任一镜像拉取失败时，不要修改 DSM 运行中的项目，先回到 GitHub/GHCR 发布流程排查。

## 先做独立备份

首次切换前必须保留一份独立于 updater 的备份，至少包含：

- 当前 `.env`
- 当前 `compose.yml`
- 当前 PostgreSQL 备份
- 当前 uploads 备份

建议命令：

```bash
export FINREC_BACKUP_STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
export FINREC_BACKUP_DIR="${FINREC_BACKUP_ROOT}/${FINREC_BACKUP_STAMP}"
export FINREC_BACKUP_MANIFEST="${FINREC_BACKUP_DIR}/backup-manifest.env"
mkdir -p "$FINREC_BACKUP_DIR"
cp "${FINREC_LEGACY_APP_DIR}/.env" "${FINREC_BACKUP_DIR}/.env"
cp "${FINREC_LEGACY_APP_DIR}/compose.yml" "${FINREC_BACKUP_DIR}/compose.yml"
docker compose \
  --project-name "${FINREC_LEGACY_COMPOSE_PROJECT}" \
  --env-file "${FINREC_LEGACY_APP_DIR}/.env" \
  -f "${FINREC_LEGACY_APP_DIR}/compose.yml" \
  exec -T web /app/scripts/backup.sh > "${FINREC_BACKUP_MANIFEST}"
eval "$(
  python3 - "${FINREC_BACKUP_MANIFEST}" <<'PY'
import re
import shlex
import sys
from pathlib import Path

payload = Path(sys.argv[1]).read_text(encoding="utf-8").splitlines()
values = {}
for line in payload:
    key, _, value = line.partition("=")
    if key in values or not value:
        raise SystemExit("invalid backup manifest")
    values[key] = value
if set(values) != {"DB_BACKUP", "UPLOADS_BACKUP"}:
    raise SystemExit("invalid backup manifest keys")
db_path = values["DB_BACKUP"]
uploads_path = values["UPLOADS_BACKUP"]
db_match = re.fullmatch(r"/data/backups/db-[0-9]{8}-[0-9]{6}\.dump", db_path)
uploads_match = re.fullmatch(r"/data/backups/uploads-[0-9]{8}-[0-9]{6}\.tar\.gz", uploads_path)
if db_match is None or uploads_match is None:
    raise SystemExit("invalid backup paths")
print(f'export FINREC_DB_BACKUP_PATH={shlex.quote(db_path)}')
print(f'export FINREC_UPLOADS_BACKUP_PATH={shlex.quote(uploads_path)}')
PY
)"
docker compose \
  --project-name "${FINREC_LEGACY_COMPOSE_PROJECT}" \
  --env-file "${FINREC_LEGACY_APP_DIR}/.env" \
  -f "${FINREC_LEGACY_APP_DIR}/compose.yml" \
  exec -T web test -s "${FINREC_DB_BACKUP_PATH}"
docker compose \
  --project-name "${FINREC_LEGACY_COMPOSE_PROJECT}" \
  --env-file "${FINREC_LEGACY_APP_DIR}/.env" \
  -f "${FINREC_LEGACY_APP_DIR}/compose.yml" \
  exec -T web test -s "${FINREC_UPLOADS_BACKUP_PATH}"
export FINREC_LEGACY_WEB_CONTAINER="$(docker compose \
  --project-name "${FINREC_LEGACY_COMPOSE_PROJECT}" \
  --env-file "${FINREC_LEGACY_APP_DIR}/.env" \
  -f "${FINREC_LEGACY_APP_DIR}/compose.yml" \
  ps -q web)"
docker cp "${FINREC_LEGACY_WEB_CONTAINER}:${FINREC_DB_BACKUP_PATH}" "${FINREC_BACKUP_DIR}/db.dump"
docker cp "${FINREC_LEGACY_WEB_CONTAINER}:${FINREC_UPLOADS_BACKUP_PATH}" "${FINREC_BACKUP_DIR}/uploads.tar.gz"
printf 'db_backup_verified=true\nuploads_backup_verified=true\n' > "${FINREC_BACKUP_DIR}/validation.txt"
```

要求：

- 旧项目的 PostgreSQL 只能保留这一份生产实例，切换前必须确认不存在第二个数据库容器或第二份数据目录。
- 切换完成前不要删除旧的本地构建 Web 镜像。
- `validation.txt` 只记录非敏感校验结果；不要把容器内部备份路径、真实用户名、Token 或业务数据抄入人工记录。

## 首次镜像部署

确认公开镜像和独立备份都完成后，使用仓库内脚本执行首次切换：

```bash
env \
  FINREC_APP_DIR="$FINREC_APP_DIR" \
  FINREC_DATA_DIR="$FINREC_DATA_DIR" \
  FINREC_WEB_IMAGE_TAG="$FINREC_WEB_IMAGE_TAG" \
  FINREC_UPDATER_IMAGE_TAG="$FINREC_UPDATER_IMAGE_TAG" \
  FINREC_UPDATER_TOKEN="$FINREC_UPDATER_TOKEN" \
  FINREC_DEPLOY_MODE="$FINREC_DEPLOY_MODE" \
  FINREC_LEGACY_APP_DIR="$FINREC_LEGACY_APP_DIR" \
  FINREC_LEGACY_DATA_DIR="$FINREC_LEGACY_DATA_DIR" \
  FINREC_LEGACY_DATABASE_NAME="$FINREC_LEGACY_DATABASE_NAME" \
  FINREC_LEGACY_DATABASE_ROLE="$FINREC_LEGACY_DATABASE_ROLE" \
  bash scripts/deploy-dsm.sh
```

`scripts/deploy-dsm.sh` 的首次切换模式会：

- 停掉旧项目的 `db` 和 `web`，并正向确认旧数据库已停止
- 将原数据目录原子迁移到 `FINREC_DATA_DIR`，同时迁移数据库和 role identity
- 启动目标 `finance-reconciliation` 项目的 `db`、`web`、`updater`
- 复用现有 PostgreSQL、uploads、exports、backups 数据
- 执行迁移并等待 `web`、`updater` 健康

如果脚本在停止旧项目之后失败，不要手动清理镜像；先按 [system-update-runbook.md](system-update-runbook.md) 的恢复章节回退。

## 首次 Owner 启动

首次镜像切换完成后，使用标准输入初始化 Owner 账户：

```bash
export BOOTSTRAP_OWNER_USERNAME="<owner-username>"
read -rsp "Owner password: " FINREC_OWNER_PASSWORD && printf '\n'
printf '%s\n' "$FINREC_OWNER_PASSWORD" | docker compose \
  --project-name finance-reconciliation \
  --env-file "${FINREC_APP_DIR}/.env" \
  -f "${FINREC_APP_DIR}/compose.yml" \
  exec -T \
  -e BOOTSTRAP_OWNER_USERNAME="${BOOTSTRAP_OWNER_USERNAME}" \
  web python manage.py bootstrap_owner_user \
    --username "${BOOTSTRAP_OWNER_USERNAME}" \
    --password-stdin
unset FINREC_OWNER_PASSWORD
```

该命令必须通过 stdin 传递口令；不要把密码写进命令参数、`.env`、文档或 shell 历史。

## 首次切换后的最小验证

完成 `v0.2.0` 首次镜像部署后，至少验证：

- `${FINREC_BASE_URL}/accounts/login/` 可访问
- Owner 能登录并打开 `${FINREC_BASE_URL}/system/update/`
- 导入中心、发票台账和健康检查页面仍可读取
- 旧本地构建 Web 镜像仍被保留，直到 DSM smoke 全部完成

真实 DSM smoke、cleanup pending、manual intervention、后续 Web 升级与 updater 受控换 tag 流程见 [system-update-runbook.md](system-update-runbook.md)。
