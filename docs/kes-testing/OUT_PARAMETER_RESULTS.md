# OUT parameter verification

Date: 2026-11-03. Server: local KES V009R001C010, MySQL / Oracle /
SQL Server compatibility modes. Database: `test`.

This is the historical OUT-binding change report. Subsequent supplemental
testing and the current full-regression result are recorded in
`tests/kes/procedures_and_results/README.md`. In particular, OUT parameters
combined with multiple query result sets fail; the passing OUT-only cases
below do not establish support for that combination.

## Change

`Connection.prepare()` accepts the optional KES-only keyword
`parameter_modes=('in', 'inout', 'out')`. Entries correspond to bind slots
`$1`, `$2`, `$3`, not to returned columns. The driver declares directions in
Parse, leaves actual type OIDs to the server, and uses existing codecs and
prepared-statement execution. No business SQL or argument value is interpolated
or rewritten. Existing behavior remains unchanged when this keyword is omitted.

For a procedure which adds its first argument to its second argument and sets
its third argument to `done`:

```python
stmt = await con.prepare(
    'CALL demo_call($1, $2, $3)',
    parameter_modes=('in', 'inout', 'out'),
)
row = await stmt.fetchrow(2, 5, None)
```

Verified outputs with the INTEGER procedure declarations in the tests:

| Mode | `tuple(row)` |
| --- | --- |
| MySQL | `(7, 'done')` |
| Oracle | `(7, 'done')` |
| SQL Server | `(0, 7, 'done')`; first field is `_retval_` |

This is explicit parameter binding support, not automatic inference of every
procedure signature. MySQL and SQL Server callers must use the explicit
declaration for these output scenarios. It is not a complete stored-procedure
compatibility layer.

## Added Tests

All added tests are in
`tests/kes/execution_transactions_statements/test_execution_transactions_statements.py`.

| Scenario | Cases | Result |
| --- | ---: | --- |
| Three-mode CALL with IN/INOUT/OUT; cache 0/100; repeated calls, NULL, fetchmany, executemany; SQL Server EXEC as well | 6 | Passed |
| Oracle anonymous-block INSERT/UPDATE/DELETE RETURNING INTO, duplicate-key recovery, quote-containing input, rollback and table contents | 2 | Passed |
| Invalid direction declarations and counts, rejected without inserting rows; connection remains usable | 18 | Passed |
| Oracle numeric/timestamp/NULL output, zero-row and multirow errors, rollback and table contents | 2 | Passed |
| Standalone Oracle RETURNING INTO server rejection; no row inserted; ordinary RETURNING succeeds | 1 | Passed |

```bash
ASYNCKB_KES_PASSWORD='<test password>' PYTHONPATH=. pytest -q \
  tests/kes/execution_transactions_statements/test_execution_transactions_statements.py \
  -k 'explicit_parameter_directions or dml_returning_into or invalid_parameter_directions or returning_into_temporal or standalone_returning_into' \
  --kes-mode all --tb=short
```

Observed: `29 passed, 138 deselected`.

## Oracle Context Restrictions

Standalone `INSERT ... RETURNING id INTO $2` is rejected by this server with
SQLSTATE `42601`, including when Parse explicitly declares the output slot.
The driver does not silently wrap arbitrary SQL.

The verified output-binding form is:

```python
stmt = await con.prepare(
    'BEGIN INSERT INTO demo_output VALUES ($1) RETURNING id INTO $2; END;',
    parameter_modes=('in', 'out'),
)
assert await stmt.fetchval(42, None) == 42
```

The anonymous block also supports UPDATE and DELETE outputs. No matching row
raises `NoDataFoundError`; multiple matching rows with scalar output raise
`TooManyRowsError`. These server errors are preserved. Ordinary
`INSERT ... RETURNING id` still works without INTO or an anonymous block.

## Full Regression

```bash
ASYNCKB_KES_PASSWORD='<test password>' PYTHONPATH=. pytest -q tests/kes --kes-mode all --tb=short
```

Observed: `3 failed, 473 passed in 37.42s`.

The remaining known failures are
`test_sqlserver_bound_multistatement_dml_and_rollback` with variants
`executemany`, `fetchmany`, and `prepared`. They concern failed multi-statement
batches retaining changes without an explicit transaction. They were not fixed
or removed by this OUT-binding change. The full suite is therefore **not** all
green. This report does not claim all procedure syntax, modes, output types,
result-set combinations, or KES versions have been verified.
