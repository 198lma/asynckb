# KingbaseES test suite

This directory contains the complete test suite for the adapted asynckb
driver. Tests target only the KingbaseES MySQL, Oracle, and SQL Server
compatibility modes.

## Structure

The seven logical modules mirror the six adaptation modules plus authentication. Each directory
contains focused unit checks and database-backed checks, so a requirement
can be reviewed and run independently. Placeholder conversion has its own
test file within the protocol module.

| Test directory | Test file | Requirement covered |
| --- | --- | --- |
| `connection_initialization/` | `test_connection_initialization.py` | Connection parameters, service files, mode detection, handshake, and initialization failures |
| `protocol_and_async/` | `test_protocol_and_async.py`, `test_placeholders.py` | Protocol scheduling, COPY, notifications, timeout races, CALL detection and mode placeholder conversion |
| `types_and_codecs/` | `test_types_and_codecs.py` | KES type/OID discovery, codecs, custom codecs, type matrices, and type-related transactions |
| `execution_transactions_statements/` | `test_execution_transactions_statements.py` | Query execution, transactions, prepared statements, cursors, schema objects, and stored procedures |
| `pool/` | `test_pool.py` | Connection pool lifecycle, callbacks, recycling, cancellation, concurrency, and public pool APIs |
| `sqlalchemy_dialect/` | `test_sqlalchemy_dialect.py` | SQLAlchemy async dialect, reflection, compilation, and transactions |
| `procedures_and_results/` | `test_procedures.py`, `test_multiple_results.py` | EXEC routine/OUT/function and SQL Server ZIP scenarios; see local README for limitations |
| `authentication/` | `test_authentication.py`, `test_external_authentication.py`, `test_mac*.py` | AUTH real authentication, external services, certificate/OS identities and MAC whitelist verification |
| `support/` | Shared configuration, fixtures, and framework helpers |

Every test function has one responsibility and starts its docstring with
`测试点：`. Mode-independent tests use `kes_config`; mode-specific behavior
uses `mysql_config`, `oracle_config`, or `sqlserver_config`.

Native asynchronous workflow tests are declared with `async def` and the
`pytest.mark.asyncio` marker. Lower-level regression tests may retain an
explicit `asyncio.run()` wrapper when event-loop ownership is itself part of
the contract under test.

## Commands

### Test-plan IDs

All 160 active test points retain the IDs in the test plan and XMind. Each test
function has a `@pytest.mark.case_id("KB-EXEC-049")` marker. Parameterized
mode/cache/input combinations share their test-point ID; their pytest
parameter suffix distinguishes individual executions. The seven logical
modules include procedure/result scenarios under EXEC and package identity
under CONN, without changing the existing numbering.
`KB-AUTH-014` (PAM login) was removed because the three supplied KES builds
do not support PAM; its retired ID is not reused. PAM/BSD availability checks
are also retired; these limitations remain documented, not counted as passes.
The 2026-11-19 reduction retired 71 points. Decisions are recorded in
`docs/kes-testing/CASE_REDUCTION.json`; no surviving IDs were renumbered.

See the [complete ID-to-source index](../../docs/kes-testing/TEST_CASE_INDEX.md).
The manifest in `case_manifest.json` records the same ID, title and function
mapping. Collection rejects missing, duplicate or mismatched markers.

```bash
# Locate all parameter combinations of one test-plan point.
python -m pytest tests/kes -k KB-EXEC-049 --collect-only -q

# Execute that point; JUnit properties retain case_id/title/source.
ASYNCKB_KES_PASSWORD='<password>' python -m pytest tests/kes \
    -k KB-EXEC-049 -v --junitxml=kes-test-results.xml

# Check every source mapping and index without a database.
python3 tools/check_test_traceability.py
```

When adding or moving a test, update its plan/XMind entry, marker and manifest,
then regenerate source links with
`python3 tools/check_test_traceability.py --write-index`.

### Suite Commands

```bash
# Collect the complete seven-module suite without connecting to KES.
PYTHONPATH=. pytest --collect-only -q tests/kes/*/test_*.py

# Run unit checks only.
PYTHONPATH=. pytest -q -m unit tests/kes/*/test_*.py

# Run one requirement module.
ASYNCKB_KES_PASSWORD='<password>' PYTHONPATH=. \
    pytest -q tests/kes/types_and_codecs/test_types_and_codecs.py

# Run against configured KES instances (authentication requires flags below).
ASYNCKB_KES_PASSWORD='<password>' PYTHONPATH=. \
    pytest -q tests/kes/*/test_*.py

# Run EXEC stored-procedure / multi-result scenarios.
ASYNCKB_KES_PASSWORD='<password>' PYTHONPATH=. \
    pytest -q tests/kes/procedures_and_results --kes-mode all
```

Routine/result tests belong to EXEC; authentication belongs to AUTH.
The all-suite command includes both directories. The six pre-existing OUT/multiple-result
combinations are strict expected failures, restricted to `ProtocolError`:
other exceptions fail, and unexpected success also fails pending review.
They are reported separately, never counted as supported functionality.
See [the current-version report](../../docs/kes-testing/NEW_VERSION_RESULTS.md)
for database versions, type expectations, and remaining restrictions.
Authentication requires explicit setup flags; ordinary runs skip tests that
would alter HBA or start disposable instances. See
[authentication instructions](authentication/README.md) and
[actual authentication results](../../docs/kes-testing/AUTHENTICATION_RESULTS.md).

## Complete Local Regression Without Skipped Cases

Run the two non-overlapping batches below against the local test environment.
The first includes password authentication and temporarily configures test
roles/HBA rules; the second creates disposable instances in a network
namespace. Both restore their changes. SQL Server ROWVERSION uses a unique
temporary database created from `master`, so its test account needs database
creation/deletion privileges. The regular database remains `test`.

```bash
ASYNCKB_KES_PASSWORD='<password>' PYTHONPATH=. python3 -m pytest tests/kes \
    --kes-mode all --kes-auth-configure-server \
    --ignore=tests/kes/authentication/test_external_authentication.py \
    --ignore=tests/kes/authentication/test_mac.py \
    --ignore=tests/kes/authentication/test_mac_whitelist.py \
    -q --assert=rewrite -rs -o junit_family=legacy \
    --junitxml=full-suite-results.xml

python3 -m pip install -r tests/kes/authentication/requirements.txt
PYTHONPATH=. python3 -m tests.kes.authentication.run_isolated \
    --kes-mode all -rs -o junit_family=legacy \
    --junitxml=isolated-suite-results.xml
```

The 2026-11-19 rerun produced `615 passed, 6 xfailed` and `48 passed`:
669 nodes in total (663 passed), with zero skips. The six strict expected failures still
document the unsupported OUT/multiple-result combination and are not passes.

Performance/stress is separate: seven scenarios across three modes (21 groups),
1,901,403 successful operations and zero errors. See
`docs/kes-testing/PERFORMANCE_RESULTS.md`; the sustained phase is 120 seconds
per mode, not a long-duration soak test.
