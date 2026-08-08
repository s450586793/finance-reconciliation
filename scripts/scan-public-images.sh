#!/usr/bin/env bash
set -euo pipefail

project_root="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd -P)"

if [ "$#" -lt 2 ]; then
  exit 1
fi

for variable in DOCKER_HOST DOCKER_CONTEXT DOCKER_TLS DOCKER_TLS_VERIFY DOCKER_CERT_PATH DOCKER_CONFIG; do
  if [ -n "${!variable:-}" ]; then
    exit 1
  fi
done

anchor_file=$1
shift
anchor_mode="$(stat -c '%a' -- "$anchor_file" 2>/dev/null)" || exit 1
anchor_path="$(readlink -f -- "$anchor_file" 2>/dev/null)" || exit 1
if [ -L "$anchor_file" ] || [ ! -f "$anchor_file" ] || [ "$anchor_mode" != "600" ]; then
  exit 1
fi
case "$anchor_path" in
  "$project_root"|"$project_root"/*) exit 1 ;;
esac

umask 077
scratch_dir="$(mktemp -d)"
chmod 700 -- "$scratch_dir"
container_id=""

cleanup() {
  local status=$?
  trap - EXIT
  if [ -n "$container_id" ]; then
    docker rm "$container_id" >/dev/null 2>&1 || :
  fi
  rm -rf -- "$scratch_dir"
  exit "$status"
}
trap cleanup EXIT

index=0
for image in "$@"; do
  docker image inspect "$image" >"$scratch_dir/inspect-$index.json" 2>/dev/null
  docker history --no-trunc "$image" >"$scratch_dir/history-$index.txt" 2>/dev/null
  container_output="$(docker create "$image" 2>/dev/null)"
  container_id="${container_output%%$'\n'*}"
  case "$container_output" in
    ''|*$'\n'*) exit 1 ;;
  esac
  docker export "$container_id" >"$scratch_dir/filesystem-$index.tar" 2>/dev/null
  docker rm "$container_id" >/dev/null 2>&1
  container_id=""
  python3 "$project_root/scripts/scan-public-tree.py" "$scratch_dir" "$anchor_file" >/dev/null 2>&1
  index=$((index + 1))
done

printf 'public image scan passed\n'
