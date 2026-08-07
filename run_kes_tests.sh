#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

profile="all"
if [[ "${1:-}" =~ ^(unit|integration|framework|all)$ ]]; then
    profile="$1"
    shift
fi

case "$profile" in
    unit) test_path="tests/kes/unit" ;;
    integration) test_path="tests/kes/integration" ;;
    framework) test_path="tests/kes/framework" ;;
    all) test_path="tests/kes" ;;
esac

if [[ "$profile" != "unit" && -z "${ASYNCPG_KES_PASSWORD:-}" ]]; then
    echo "ASYNCPG_KES_PASSWORD is required" >&2
    exit 2
fi

cd "$project_dir"
exec python3 -m pytest "$test_path" "$@"
