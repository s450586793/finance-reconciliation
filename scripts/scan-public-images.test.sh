#!/usr/bin/env bash
set -euo pipefail

project_root="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd -P)"
tool_path="$project_root/scripts/scan-public-images.sh"
suite_dir="$(mktemp -d)"

cleanup_suite() {
  local status=$?
  trap - EXIT
  rm -rf -- "$suite_dir"
  exit "$status"
}
trap cleanup_suite EXIT

fail_test() {
  printf '%s\n' "$1" >&2
  exit 1
}

[ -x "$tool_path" ] || fail_test "missing executable public image scan tool"

write_fake_docker() {
  local mode=$1
  cat >"$suite_dir/bin/docker" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

case "$1" in
  image)
    [ "$2" = "inspect" ] || exit 90
    case "${FAKE_DOCKER_MODE:-clean}" in
      inspect-anchor) printf '%s\n' '{"config":"PRIVATE-COMPANY"}' ;;
      missing-image) exit 1 ;;
      *) printf '%s\n' '{"config":"public"}' ;;
    esac
    ;;
  history)
    case "${FAKE_DOCKER_MODE:-clean}" in
      history-anchor) printf '%s\n' 'PRIVATE-COMPANY history' ;;
      *) printf '%s\n' 'public history' ;;
    esac
    ;;
  create)
    case "${FAKE_DOCKER_MODE:-clean}" in
      multiline-id) printf '%s\n%s\n' 'container-one' 'container-two' ;;
      missing-image) exit 1 ;;
      *) printf '%s\n' 'container-one' ;;
    esac
    ;;
  export)
    case "${FAKE_DOCKER_MODE:-clean}" in
      failed-export) printf '%s\n' 'PRIVATE-COMPANY export failure' >&2; exit 1 ;;
      filesystem-anchor) tar -C "$FAKE_DOCKER_DATA" -cf - private.txt ;;
      *) tar -C "$FAKE_DOCKER_DATA" -cf - public.txt ;;
    esac
    ;;
  rm) printf '%s\n' "$2" >>"$FAKE_DOCKER_REMOVALS" ;;
  *) exit 91 ;;
esac
EOF
  chmod 755 "$suite_dir/bin/docker"
  FAKE_DOCKER_MODE="$mode"
}

run_scan() {
  local mode=$1
  shift
  write_fake_docker "$mode"
  FAKE_DOCKER_MODE="$mode" \
  FAKE_DOCKER_DATA="$suite_dir/data" \
  FAKE_DOCKER_REMOVALS="$suite_dir/removals" \
  PATH="$suite_dir/bin:$PATH" \
  "$tool_path" "$suite_dir/anchors.txt" "$@"
}

mkdir -p "$suite_dir/bin" "$suite_dir/data"
printf 'public\n' >"$suite_dir/data/public.txt"
printf 'PRIVATE-COMPANY\n' >"$suite_dir/data/private.txt"
printf 'private-company\n' >"$suite_dir/anchors.txt"
chmod 600 "$suite_dir/anchors.txt"

fixture_project="$suite_dir/project"
mkdir -p "$fixture_project/scripts"
cp "$tool_path" "$fixture_project/scripts/scan-public-images.sh"
cp "$project_root/scripts/scan-public-tree.py" "$fixture_project/scripts/scan-public-tree.py"
cp "$project_root/scripts/public_scan.py" "$fixture_project/scripts/public_scan.py"
chmod 755 "$fixture_project/scripts/scan-public-images.sh"
printf 'private-company\n' >"$fixture_project/anchors.txt"
chmod 600 "$fixture_project/anchors.txt"
write_fake_docker clean
set +e
FAKE_DOCKER_DATA="$suite_dir/data" \
  FAKE_DOCKER_REMOVALS="$suite_dir/removals" \
  PATH="$suite_dir/bin:$PATH" \
  "$fixture_project/scripts/scan-public-images.sh" "$fixture_project/anchors.txt" public:image \
  >"$suite_dir/project-anchor.stdout" 2>"$suite_dir/project-anchor.stderr"
status=$?
set -e
[ "$status" -ne 0 ] || fail_test "anchor within project root must fail"
[ ! -s "$suite_dir/project-anchor.stdout" ] || fail_test "project anchor failure must not print output"
[ ! -s "$suite_dir/project-anchor.stderr" ] || fail_test "project anchor failure must not print errors"

output="$(run_scan clean public:first public:second)" || fail_test "clean images must pass"
[ "$output" = "public image scan passed" ] || fail_test "image scanner must print its fixed success message"

for mode in inspect-anchor history-anchor filesystem-anchor missing-image multiline-id failed-export; do
  : >"$suite_dir/removals"
  set +e
  run_scan "$mode" "private:image" >"$suite_dir/$mode.stdout" 2>"$suite_dir/$mode.stderr"
  status=$?
  set -e
  [ "$status" -ne 0 ] || fail_test "$mode must fail"
  ! grep -Fq 'PRIVATE-COMPANY' "$suite_dir/$mode.stdout" "$suite_dir/$mode.stderr" || fail_test "$mode leaked an anchor"
  ! grep -Fq 'private:image' "$suite_dir/$mode.stdout" "$suite_dir/$mode.stderr" || fail_test "$mode leaked an image reference"
done

[ "$(cat "$suite_dir/removals")" = "container-one" ] || fail_test "created container must be removed after export failure paths"

chmod 644 "$suite_dir/anchors.txt"
set +e
run_scan clean public:image >"$suite_dir/insecure-anchor.stdout" 2>"$suite_dir/insecure-anchor.stderr"
status=$?
set -e
[ "$status" -ne 0 ] || fail_test "insecure anchor file must fail"
chmod 600 "$suite_dir/anchors.txt"

set +e
DOCKER_HOST='tcp://private.example.invalid' \
  FAKE_DOCKER_DATA="$suite_dir/data" \
  FAKE_DOCKER_REMOVALS="$suite_dir/removals" \
  PATH="$suite_dir/bin:$PATH" \
  "$tool_path" "$suite_dir/anchors.txt" public:image >"$suite_dir/docker-host.stdout" 2>"$suite_dir/docker-host.stderr"
status=$?
set -e
[ "$status" -ne 0 ] || fail_test "ambient Docker overrides must fail"

printf 'public image scan contract passed\n'
