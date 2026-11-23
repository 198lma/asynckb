#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

profile="all"
if [[ "${1:-}" =~ ^(unit|connection|protocol|types|execution|pool|sqlalchemy|all)$ ]]; then
    profile="$1"
    shift
fi

case "$profile" in
    unit) test_path="tests/kes/test_*.py tests/kes/*/test_*.py"; extra_args=(-m unit) ;;
    connection) test_path="tests/kes/connection_initialization/test_connection_initialization.py"; extra_args=() ;;
    protocol) test_path="tests/kes/protocol_and_async/test_protocol_and_async.py"; extra_args=() ;;
    types) test_path="tests/kes/types_and_codecs/test_types_and_codecs.py"; extra_args=() ;;
    execution) test_path="tests/kes/execution_transactions_statements/test_execution_transactions_statements.py"; extra_args=() ;;
    pool) test_path="tests/kes/pool/test_pool.py"; extra_args=() ;;
    sqlalchemy) test_path="tests/kes/sqlalchemy_dialect/test_sqlalchemy_dialect.py"; extra_args=() ;;
    all) test_path="tests/kes/test_*.py tests/kes/*/test_*.py"; extra_args=() ;;
esac

collect_only=false
for arg in "$@"; do
    if [[ "$arg" == "--collect-only" || "$arg" == "--co" ]]; then
        collect_only=true
        break
    fi
done

if [[ "$profile" != "unit" && "$collect_only" == false && -z "${ASYNCKB_KES_PASSWORD:-}" ]]; then
    echo "ASYNCKB_KES_PASSWORD is required" >&2
    exit 2
fi

cd "$project_dir"
PYTHONPATH="$project_dir${PYTHONPATH:+:$PYTHONPATH}" \
    exec python3 -m pytest "${extra_args[@]}" $test_path "$@"
