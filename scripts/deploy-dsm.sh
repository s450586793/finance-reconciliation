#!/usr/bin/env sh
set -eu

target_project="finance-reconciliation"
legacy_project="app"
deployment_root="/volume4/docker/docker"
default_app_dir="/volume4/docker/docker/finance-reconciliation/app"
default_data_dir="/volume4/docker/docker/finance-reconciliation/data"
required_target_owner_uid="0"
deploy_mode="${FINREC_DEPLOY_MODE:-upgrade}"
health_max_attempts="${FINREC_HEALTH_MAX_ATTEMPTS:-30}"
health_sleep_seconds="${FINREC_HEALTH_SLEEP_SECONDS:-2}"

failure_category="deployment failed"
failure_code=1
legacy_db_id=""
legacy_web_id=""
target_db_id=""
target_db_ids=""
legacy_restore_needed=0
data_move_started=0
target_db_start_attempted=0
identifiers_may_need_rollback=0
rendered_json=""
FINREC_TARGET_DATABASE_NAME="finance_reconciliation"
FINREC_TARGET_DATABASE_ROLE="finance"
FINREC_IDENTITY_MIGRATION_ROLE="finance_reconciliation_identity_migrator"
export FINREC_TARGET_DATABASE_NAME
export FINREC_TARGET_DATABASE_ROLE
export FINREC_IDENTITY_MIGRATION_ROLE

set_failure() {
  failure_category="$1"
  failure_code="${2:-1}"
  exit "$failure_code"
}

require_value() {
  name="$1"
  eval "value=\${$name-}"
  [ -n "$value" ] || set_failure "deployment input rejected" 2
}

require_version() {
  name="$1"
  eval "value=\${$name-}"
  printf '%s' "$value" | grep -Eq '^v[0-9]+\.[0-9]+\.[0-9]+$' || {
    set_failure "deployment input rejected" 2
  }
}

require_private_token() {
  name="$1"
  eval "value=\${$name-}"
  TOKEN_VALUE="$value" python3 -I -S 2>/dev/null <<'PY' || {
import os
import sys

value = os.environ.get("TOKEN_VALUE", "")
try:
    valid = bool(value.strip()) and len(value.encode("utf-8")) >= 32
except UnicodeError:
    valid = False
sys.exit(0 if valid else 1)
PY
    set_failure "deployment input rejected" 2
  }
}

canonical_dir() {
  (
    cd "$1" >/dev/null 2>&1 || exit 1
    pwd -P
  )
}

is_within_deployment_root() {
  case "$1" in
    "$deployment_root"/*) return 0 ;;
    *) return 1 ;;
  esac
}

target_compose() {
  docker compose \
    --project-name "$target_project" \
    --env-file "$env_file" \
    -f "$compose_file" \
    "$@"
}

legacy_compose() {
  docker compose \
    --project-name "$legacy_project" \
    --env-file "$legacy_env_file" \
    -f "$legacy_compose_file" \
    "$@"
}

valid_container_id() {
  case "$1" in
    "" | *[!a-zA-Z0-9_.:-]*) return 1 ;;
    *) return 0 ;;
  esac
}

single_running_container_id() {
  project_kind="$1"
  service_name="$2"
  if [ "$project_kind" = "legacy" ]; then
    candidate="$(legacy_compose ps -q "$service_name" 2>/dev/null)" || return 1
  else
    candidate="$(target_compose ps -q "$service_name" 2>/dev/null)" || return 1
  fi
  case "$candidate" in
    "" | *'
'*) return 1 ;;
  esac
  valid_container_id "$candidate" || return 1
  printf '%s' "$candidate"
}

all_target_container_ids() {
  target_compose ps --all -q "$1" 2>/dev/null
}

container_running_state() {
  docker inspect -f '{{.State.Running}}' "$1" 2>/dev/null
}

wait_healthy() {
  service_name="$1"
  attempt=0
  while [ "$attempt" -lt "$health_max_attempts" ]; do
    container_id="$(single_running_container_id target "$service_name" 2>/dev/null || true)"
    if [ -n "$container_id" ]; then
      health_status="$(
        docker inspect -f '{{.State.Health.Status}}' "$container_id" 2>/dev/null || true
      )"
      [ "$health_status" = "healthy" ] && return 0
    fi
    attempt=$((attempt + 1))
    [ "$attempt" -ge "$health_max_attempts" ] || {
      sleep "$health_sleep_seconds" >/dev/null 2>&1 || return 1
    }
  done
  return 1
}

validate_target_files() {
  [ "$app_dir" = "$default_app_dir" ] || return 1
  [ "$data_dir" = "$default_data_dir" ] || return 1
  [ ! -L "$app_dir" ] && [ -d "$app_dir" ] || return 1
  [ "$(canonical_dir "$app_dir")" = "$default_app_dir" ] || return 1
  [ -f "$compose_file" ] && [ ! -L "$compose_file" ] || return 1
  [ -f "$env_file" ] && [ ! -L "$env_file" ] || return 1
  TARGET_APP_DIR="$app_dir" \
    TARGET_COMPOSE_FILE="$compose_file" \
    TARGET_ENV_FILE="$env_file" \
    REQUIRED_TARGET_OWNER_UID="$required_target_owner_uid" \
    python3 -I -S 2>/dev/null <<'PY'
import os
import stat
import sys
from pathlib import Path

try:
    required_uid = int(os.environ["REQUIRED_TARGET_OWNER_UID"])
    app = Path(os.environ["TARGET_APP_DIR"]).lstat()
    compose = Path(os.environ["TARGET_COMPOSE_FILE"]).lstat()
    environment = Path(os.environ["TARGET_ENV_FILE"]).lstat()
except (KeyError, OSError, ValueError):
    sys.exit(1)

if (
    not stat.S_ISDIR(app.st_mode)
    or app.st_uid != required_uid
    or stat.S_IMODE(app.st_mode) & 0o022
    or not stat.S_ISREG(compose.st_mode)
    or compose.st_uid != required_uid
    or stat.S_IMODE(compose.st_mode) & 0o022
    or not stat.S_ISREG(environment.st_mode)
    or environment.st_uid != required_uid
    or stat.S_IMODE(environment.st_mode) != 0o600
):
    sys.exit(1)
PY
}

validate_identity_paths() {
  [ ! -L "$legacy_app_dir" ] && [ -d "$legacy_app_dir" ] || return 1
  [ ! -L "$legacy_data_dir" ] && [ -d "$legacy_data_dir" ] || return 1
  resolved_legacy_app="$(canonical_dir "$legacy_app_dir")" || return 1
  resolved_legacy_data="$(canonical_dir "$legacy_data_dir")" || return 1
  [ "$resolved_legacy_app" = "$legacy_app_dir" ] || return 1
  [ "$resolved_legacy_data" = "$legacy_data_dir" ] || return 1
  is_within_deployment_root "$resolved_legacy_app" || return 1
  is_within_deployment_root "$resolved_legacy_data" || return 1
  [ "$legacy_data_dir" != "$data_dir" ] || return 1
  [ -f "$legacy_compose_file" ] && [ ! -L "$legacy_compose_file" ] || return 1
  [ -f "$legacy_env_file" ] && [ ! -L "$legacy_env_file" ] || return 1
  [ ! -e "$data_dir" ] && [ ! -L "$data_dir" ] || return 1

  target_parent="${data_dir%/*}"
  source_parent="${legacy_data_dir%/*}"
  [ ! -L "$target_parent" ] && [ -d "$target_parent" ] || return 1
  [ ! -L "$source_parent" ] && [ -d "$source_parent" ] || return 1
  [ "$(canonical_dir "$target_parent")" = "$target_parent" ] || return 1
  [ "$(canonical_dir "$source_parent")" = "$source_parent" ] || return 1
  is_within_deployment_root "$target_parent" || return 1
  is_within_deployment_root "$source_parent" || return 1
  source_device="$(stat -c '%d' -- "$source_parent" 2>/dev/null)" || return 1
  target_device="$(stat -c '%d' -- "$target_parent" 2>/dev/null)" || return 1
  [ "$source_device" = "$target_device" ] || return 1
}

validate_upgrade_data() {
  [ ! -L "$data_dir" ] && [ -d "$data_dir" ] || return 1
  [ "$(canonical_dir "$data_dir")" = "$default_data_dir" ] || return 1
}

validate_postgres_data() {
  [ -d "$1/postgres" ] && [ ! -L "$1/postgres" ] || return 1
  [ -f "$1/postgres/PG_VERSION" ] && [ ! -L "$1/postgres/PG_VERSION" ]
}

prepare_private_state_directory() {
  state_directory="$data_dir/updater-state"
  STATE_DIRECTORY="$state_directory" python3 -I -S 2>/dev/null <<'PY'
import os
import stat
import sys
from pathlib import Path

path = Path(os.environ["STATE_DIRECTORY"])
try:
    path.mkdir(mode=0o700)
except FileExistsError:
    pass
except OSError:
    sys.exit(1)

flags = os.O_RDONLY | os.O_CLOEXEC | os.O_DIRECTORY | os.O_NOFOLLOW
try:
    descriptor = os.open(path, flags)
except OSError:
    sys.exit(1)
try:
    opened = os.fstat(descriptor)
    linked = path.lstat()
    os.fchmod(descriptor, 0o700)
    secured = os.fstat(descriptor)
    if (
        not stat.S_ISDIR(opened.st_mode)
        or not stat.S_ISDIR(linked.st_mode)
        or stat.S_IMODE(secured.st_mode) != 0o700
        or linked.st_dev != opened.st_dev
        or linked.st_ino != opened.st_ino
    ):
        sys.exit(1)
except OSError:
    sys.exit(1)
finally:
    os.close(descriptor)
PY
}

validate_rendered_contract() {
  rendered_json="$(mktemp "${TMPDIR:-/tmp}/finance-reconciliation-deploy.XXXXXX" 2>/dev/null)" || return 1
  if ! target_compose config --format json >"$rendered_json" 2>/dev/null; then
    rm -f -- "$rendered_json"
    rendered_json=""
    return 1
  fi
  if ! RENDERED_JSON="$rendered_json" \
    EXPECTED_POSTGRES_DIR="$data_dir/postgres" \
    EXPECTED_WEB_IMAGE="ghcr.io/s450586793/finance-reconciliation-web:${FINREC_WEB_IMAGE_TAG}" \
    EXPECTED_UPDATER_IMAGE="ghcr.io/s450586793/finance-reconciliation-updater:${FINREC_UPDATER_IMAGE_TAG}" \
    python3 -I -S 2>/dev/null <<'PY'
import json
import os
import sys
from pathlib import Path

try:
    payload = json.loads(Path(os.environ["RENDERED_JSON"]).read_text(encoding="utf-8"))
    services = payload["services"]
    if set(services) != {"db", "web", "updater"}:
        raise ValueError("unexpected service")
    db = services["db"]
    web = services["web"]
    updater = services["updater"]
except Exception:
    sys.exit(1)

db_mounts = [
    item
    for item in db.get("volumes", [])
    if isinstance(item, dict)
    and item.get("type") == "bind"
    and item.get("target") == "/var/lib/postgresql/data"
]
if len(db_mounts) != 1 or db_mounts[0].get("source") != os.environ["EXPECTED_POSTGRES_DIR"]:
    sys.exit(1)
if (
    web.get("image") != os.environ["EXPECTED_WEB_IMAGE"]
    or updater.get("image") != os.environ["EXPECTED_UPDATER_IMAGE"]
):
    sys.exit(1)
if web.get("pull_policy") != "never" or updater.get("pull_policy") != "never":
    sys.exit(1)

required_web_environment = {
    "DJANGO_SETTINGS_MODULE",
    "DJANGO_SECRET_KEY",
    "DJANGO_DEBUG",
    "DJANGO_ALLOWED_HOSTS",
    "CSRF_TRUSTED_ORIGINS",
    "DJANGO_COOKIE_SECURE",
    "COMPANY_TAX_ID",
    "FINREC_UPDATER_URL",
    "FINREC_UPDATER_TOKEN",
    "IMPORT_MAX_UPLOAD_BYTES",
    "IMPORT_MAX_ROWS",
    "DATABASE_URL",
}
web_environment = web.get("environment")
if not isinstance(web_environment, dict) or set(web_environment) != required_web_environment:
    sys.exit(1)
if (
    web_environment.get("DJANGO_SETTINGS_MODULE") != "config.settings.prod"
    or web_environment.get("DJANGO_DEBUG") != "false"
    or web_environment.get("FINREC_UPDATER_URL") != "http://updater:8090"
):
    sys.exit(1)

web_socket_count = sum(
    isinstance(item, dict) and item.get("source") == "/var/run/docker.sock"
    for item in web.get("volumes", [])
)
updater_socket_count = sum(
    isinstance(item, dict) and item.get("source") == "/var/run/docker.sock"
    for item in updater.get("volumes", [])
)
if web_socket_count != 0 or updater_socket_count != 1:
    sys.exit(1)
if updater.get("environment") != {
    "FINREC_UPDATER_TOKEN": web_environment["FINREC_UPDATER_TOKEN"],
    "FINREC_COMPOSE_PROJECT": "finance-reconciliation",
}:
    sys.exit(1)
PY
  then
    rm -f -- "$rendered_json"
    rendered_json=""
    return 1
  fi
  rm -f -- "$rendered_json"
  rendered_json=""
}

capture_legacy_state() {
  legacy_db_id="$(single_running_container_id legacy db 2>/dev/null)" || return 1
  legacy_web_id="$(single_running_container_id legacy web 2>/dev/null)" || return 1
}

require_target_absent() {
  for service_name in db web updater; do
    existing_ids="$(all_target_container_ids "$service_name" 2>/dev/null)" || return 1
    [ -z "$existing_ids" ] || return 1
  done
}

stop_legacy_and_prove_db_stopped() {
  legacy_restore_needed=1
  legacy_compose stop db web >/dev/null 2>&1 || return 1
  [ "$(container_running_state "$legacy_db_id" 2>/dev/null || true)" = "false" ]
}

capture_target_database() {
  target_db_ids="$(all_target_container_ids db 2>/dev/null)" || return 1
  target_db_id=""
  count=0
  for candidate in $target_db_ids; do
    valid_container_id "$candidate" || return 1
    count=$((count + 1))
    target_db_id="$candidate"
  done
  [ "$count" -eq 1 ]
}

prove_target_database_identity() {
  identity="$(
    docker inspect -f '{{ index .Config.Labels "com.docker.compose.project" }}|{{ index .Config.Labels "com.docker.compose.service" }}' \
      "$target_db_id" 2>/dev/null
  )" || return 1
  [ "$identity" = "$target_project|db" ]
}

run_psql_as_legacy_role() {
  docker exec -i \
    -e FINREC_LEGACY_DATABASE_NAME \
    -e FINREC_LEGACY_DATABASE_ROLE \
    -e FINREC_TARGET_DATABASE_NAME \
    -e FINREC_TARGET_DATABASE_ROLE \
    -e FINREC_IDENTITY_MIGRATION_ROLE \
    "$target_db_id" \
    sh -c 'PGUSER="$FINREC_LEGACY_DATABASE_ROLE" exec psql --dbname postgres'
}

run_psql_as_target_role() {
  docker exec -i \
    -e FINREC_LEGACY_DATABASE_NAME \
    -e FINREC_LEGACY_DATABASE_ROLE \
    -e FINREC_TARGET_DATABASE_NAME \
    -e FINREC_TARGET_DATABASE_ROLE \
    -e FINREC_IDENTITY_MIGRATION_ROLE \
    "$target_db_id" \
    sh -c 'PGUSER="$FINREC_TARGET_DATABASE_ROLE" exec psql --dbname postgres'
}

run_psql_as_migration_role() {
  docker exec -i \
    -e FINREC_LEGACY_DATABASE_NAME \
    -e FINREC_LEGACY_DATABASE_ROLE \
    -e FINREC_TARGET_DATABASE_NAME \
    -e FINREC_TARGET_DATABASE_ROLE \
    -e FINREC_IDENTITY_MIGRATION_ROLE \
    "$target_db_id" \
    sh -c 'PGUSER="$FINREC_IDENTITY_MIGRATION_ROLE" exec psql --dbname postgres'
}

wait_for_legacy_database_readiness() {
  attempt=0
  while [ "$attempt" -lt "$health_max_attempts" ]; do
    if run_psql_as_legacy_role >/dev/null 2>&1 <<'SQL'
\set ON_ERROR_STOP on
SELECT 1 AS database_ready;
SQL
    then
      return 0
    fi
    attempt=$((attempt + 1))
    [ "$attempt" -ge "$health_max_attempts" ] || {
      sleep "$health_sleep_seconds" >/dev/null 2>&1 || return 1
    }
  done
  return 1
}

validate_identifier_migration() {
  run_psql_as_legacy_role >/dev/null 2>&1 <<'SQL'
\set ON_ERROR_STOP on
\getenv legacy_database FINREC_LEGACY_DATABASE_NAME
\getenv legacy_role FINREC_LEGACY_DATABASE_ROLE
\getenv target_database FINREC_TARGET_DATABASE_NAME
\getenv target_role FINREC_TARGET_DATABASE_ROLE
\getenv migration_role FINREC_IDENTITY_MIGRATION_ROLE
SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'legacy_role')
       AND (:'legacy_role' = :'target_role' OR NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'target_role'))
       AND NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'migration_role') AS role_safe
\gset
\if :role_safe
\else
\quit 1
\endif
SELECT EXISTS (SELECT 1 FROM pg_database WHERE datname = :'legacy_database')
       AND (:'legacy_database' = :'target_database' OR NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = :'target_database')) AS database_safe
\gset
\if :database_safe
\else
\quit 1
\endif
SQL
}

create_identifier_migration_role() {
  run_psql_as_legacy_role >/dev/null 2>&1 <<'SQL'
\set ON_ERROR_STOP on
\getenv migration_role FINREC_IDENTITY_MIGRATION_ROLE
SELECT format('CREATE ROLE %s WITH SUPERUSER LOGIN', format('%I', :'migration_role'))
\gexec
SQL
}

migrate_identifiers() {
  validate_identifier_migration || return 1
  identifiers_may_need_rollback=1
  create_identifier_migration_role || return 1
  run_psql_as_migration_role >/dev/null 2>&1 <<'SQL' || return 1
\set ON_ERROR_STOP on
\getenv legacy_database FINREC_LEGACY_DATABASE_NAME
\getenv legacy_role FINREC_LEGACY_DATABASE_ROLE
\getenv target_database FINREC_TARGET_DATABASE_NAME
\getenv target_role FINREC_TARGET_DATABASE_ROLE
SELECT format(
    'ALTER ROLE %s RENAME TO %s',
    format('%I', :'legacy_role'),
    format('%I', :'target_role')
)
WHERE :'legacy_role' <> :'target_role'
\gexec
SELECT format(
    'ALTER DATABASE %s RENAME TO %s',
    format('%I', :'legacy_database'),
    format('%I', :'target_database')
)
WHERE :'legacy_database' <> :'target_database'
\gexec
SQL
  run_psql_as_target_role >/dev/null 2>&1 <<'SQL'
\set ON_ERROR_STOP on
\getenv migration_role FINREC_IDENTITY_MIGRATION_ROLE
SELECT format('DROP ROLE %s', format('%I', :'migration_role'))
WHERE EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'migration_role')
\gexec
SQL
}

ensure_recovery_migration_role() {
  if run_psql_as_target_role >/dev/null 2>&1 <<'SQL'
\set ON_ERROR_STOP on
\getenv migration_role FINREC_IDENTITY_MIGRATION_ROLE
SELECT format('CREATE ROLE %s WITH SUPERUSER LOGIN', format('%I', :'migration_role'))
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'migration_role')
\gexec
SQL
  then
    return 0
  fi
  run_psql_as_legacy_role >/dev/null 2>&1 <<'SQL'
\set ON_ERROR_STOP on
\getenv migration_role FINREC_IDENTITY_MIGRATION_ROLE
SELECT format('CREATE ROLE %s WITH SUPERUSER LOGIN', format('%I', :'migration_role'))
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'migration_role')
\gexec
SQL
}

rollback_identifiers() {
  [ "$identifiers_may_need_rollback" -eq 1 ] || return 0
  [ -n "$target_db_id" ] || return 1
  ensure_recovery_migration_role || return 1
  run_psql_as_migration_role >/dev/null 2>&1 <<'SQL' || return 1
\set ON_ERROR_STOP on
\getenv legacy_database FINREC_LEGACY_DATABASE_NAME
\getenv legacy_role FINREC_LEGACY_DATABASE_ROLE
\getenv target_database FINREC_TARGET_DATABASE_NAME
\getenv target_role FINREC_TARGET_DATABASE_ROLE
SELECT format(
    'ALTER DATABASE %s RENAME TO %s',
    format('%I', :'target_database'),
    format('%I', :'legacy_database')
)
WHERE :'legacy_database' <> :'target_database'
  AND EXISTS (SELECT 1 FROM pg_database WHERE datname = :'target_database')
  AND NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = :'legacy_database')
\gexec
SELECT format(
    'ALTER ROLE %s RENAME TO %s',
    format('%I', :'target_role'),
    format('%I', :'legacy_role')
)
WHERE :'legacy_role' <> :'target_role'
  AND EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'target_role')
  AND NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'legacy_role')
\gexec
SQL
  run_psql_as_legacy_role >/dev/null 2>&1 <<'SQL'
\set ON_ERROR_STOP on
\getenv migration_role FINREC_IDENTITY_MIGRATION_ROLE
SELECT format('DROP ROLE %s', format('%I', :'migration_role'))
WHERE EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'migration_role')
\gexec
SQL
}

stop_target_clients() {
  target_compose stop web updater >/dev/null 2>&1 || return 1
  for service_name in web updater; do
    running_ids="$(target_compose ps -q "$service_name" 2>/dev/null)" || return 1
    [ -z "$running_ids" ] || return 1
  done
}

stop_target_and_prove_db_stopped() {
  cleanup_safe=1
  target_compose stop web updater db >/dev/null 2>&1 || cleanup_safe=0
  current_ids="$(all_target_container_ids db 2>/dev/null)" || cleanup_safe=0
  running_ids="$(target_compose ps -q db 2>/dev/null)" || cleanup_safe=0
  [ -z "$running_ids" ] || cleanup_safe=0
  for candidate in $target_db_ids $current_ids; do
    valid_container_id "$candidate" || {
      cleanup_safe=0
      continue
    }
    state="$(container_running_state "$candidate" 2>/dev/null)" || {
      cleanup_safe=0
      continue
    }
    [ "$state" = "false" ] || cleanup_safe=0
  done
  [ "$cleanup_safe" -eq 1 ]
}

reverse_data_move() {
  [ "$data_move_started" -eq 1 ] || return 0
  if [ -d "$legacy_data_dir" ] && [ ! -L "$legacy_data_dir" ] && \
    [ ! -e "$data_dir" ] && [ ! -L "$data_dir" ]; then
    return 0
  fi
  [ ! -e "$legacy_data_dir" ] && [ ! -L "$legacy_data_dir" ] || return 1
  [ -d "$data_dir" ] && [ ! -L "$data_dir" ] || return 1
  mv -- "$data_dir" "$legacy_data_dir" >/dev/null 2>&1
}

restore_legacy_containers() {
  [ "$legacy_restore_needed" -eq 1 ] || return 0
  docker start "$legacy_db_id" "$legacy_web_id" >/dev/null 2>&1 || return 1
  [ "$(container_running_state "$legacy_db_id" 2>/dev/null || true)" = "true" ] || return 1
  [ "$(container_running_state "$legacy_web_id" 2>/dev/null || true)" = "true" ]
}

on_signal() {
  failure_category="identity migration failed"
  exit 143
}

manual_recovery_and_exit() {
  printf '%s\n' "identity migration requires manual recovery" >&2
  exit "$1"
}

on_exit() {
  status=$?
  trap - EXIT HUP INT TERM
  [ "$status" -ne 0 ] || exit 0
  set +e
  if [ -n "$rendered_json" ]; then
    rm -f -- "$rendered_json" >/dev/null 2>&1
    rendered_json=""
  fi

  if [ "$deploy_mode" = "identity-migration" ]; then
    if [ "$target_db_start_attempted" -eq 1 ]; then
      stop_target_clients || manual_recovery_and_exit "$status"
      rollback_identifiers || manual_recovery_and_exit "$status"
      stop_target_and_prove_db_stopped || manual_recovery_and_exit "$status"
    fi
    reverse_data_move || manual_recovery_and_exit "$status"
    if [ "$legacy_restore_needed" -eq 1 ]; then
      restore_legacy_containers || manual_recovery_and_exit "$status"
    fi
  fi
  printf '%s\n' "$failure_category" >&2
  exit "$status"
}

trap on_exit EXIT
trap on_signal HUP INT TERM

command -v python3 >/dev/null 2>&1 || set_failure "deployment validation failed"
require_value FINREC_APP_DIR
require_value FINREC_DATA_DIR
require_value FINREC_WEB_IMAGE_TAG
require_value FINREC_UPDATER_IMAGE_TAG
require_value FINREC_UPDATER_TOKEN
require_private_token FINREC_UPDATER_TOKEN
require_version FINREC_WEB_IMAGE_TAG
require_version FINREC_UPDATER_IMAGE_TAG

case "$deploy_mode" in
  identity-migration | upgrade) ;;
  *) set_failure "deployment input rejected" 2 ;;
esac
case "$health_max_attempts" in
  "" | *[!0-9]* | 0) set_failure "deployment input rejected" 2 ;;
esac
case "$health_sleep_seconds" in
  "" | *[!0-9]*) set_failure "deployment input rejected" 2 ;;
esac

app_dir="$FINREC_APP_DIR"
data_dir="$FINREC_DATA_DIR"
compose_file="$app_dir/compose.yml"
env_file="$app_dir/.env"

validate_target_files || set_failure "deployment validation failed"
validate_rendered_contract || set_failure "deployment validation failed"

if [ "$deploy_mode" = "identity-migration" ]; then
  require_value FINREC_LEGACY_APP_DIR
  require_value FINREC_LEGACY_DATA_DIR
  require_value FINREC_LEGACY_DATABASE_NAME
  require_value FINREC_LEGACY_DATABASE_ROLE
  legacy_app_dir="$FINREC_LEGACY_APP_DIR"
  legacy_data_dir="$FINREC_LEGACY_DATA_DIR"
  legacy_compose_file="$legacy_app_dir/compose.yml"
  legacy_env_file="$legacy_app_dir/.env"
  validate_identity_paths || set_failure "deployment validation failed"
  validate_postgres_data "$legacy_data_dir" || set_failure "deployment validation failed"
  capture_legacy_state || set_failure "deployment state conflict"
  require_target_absent || set_failure "deployment state conflict"
else
  validate_upgrade_data || set_failure "deployment validation failed"
  validate_postgres_data "$data_dir" || set_failure "deployment validation failed"
fi

target_compose pull --policy always web updater >/dev/null 2>&1 || {
  set_failure "deployment failed"
}

if [ "$deploy_mode" = "identity-migration" ]; then
  stop_legacy_and_prove_db_stopped || set_failure "identity migration failed"
  data_move_started=1
  mv -- "$legacy_data_dir" "$data_dir" >/dev/null 2>&1 || {
    set_failure "identity migration failed"
  }
  validate_postgres_data "$data_dir" || set_failure "identity migration failed"
fi

prepare_private_state_directory || set_failure "deployment validation failed"

target_db_start_attempted=1
target_up_status=0
target_compose up -d db >/dev/null 2>&1 || target_up_status=$?
capture_target_database || set_failure "deployment state conflict"
[ "$target_up_status" -eq 0 ] || set_failure "deployment failed"
prove_target_database_identity || set_failure "deployment state conflict"

if [ "$deploy_mode" = "identity-migration" ]; then
  wait_for_legacy_database_readiness || set_failure "identity migration failed"
  migrate_identifiers || set_failure "identity migration failed"
fi

wait_healthy db || set_failure "deployment failed"
target_compose run --rm --no-deps web python manage.py migrate >/dev/null 2>&1 || {
  set_failure "deployment failed"
}
target_compose up -d --no-deps updater >/dev/null 2>&1 || set_failure "deployment failed"
wait_healthy updater || set_failure "deployment failed"
target_compose up -d --no-deps web >/dev/null 2>&1 || set_failure "deployment failed"
wait_healthy web || set_failure "deployment failed"

trap - EXIT HUP INT TERM
exit 0
