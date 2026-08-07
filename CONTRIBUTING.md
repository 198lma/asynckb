# Contributing

## Development setup

Use Python 3.9 or later with a C compiler and CPython development headers.
The protocol sources are included in the repository; no Git submodule checkout
is required.

```bash
python3 -m pip install --group test
python3 -m pip install -e .
./run_kes_tests.sh unit -q
```

## KES integration tests

Integration tests require KingbaseES MySQL, Oracle, and SQL Server
compatibility instances. Export the variables listed in
`tests/kes/kes-test.env.example`; never commit their real values.

```bash
ASYNCPG_KES_PASSWORD='<password>' ./run_kes_tests.sh all -q
```

Every test function must have a single clear responsibility and a docstring
beginning with `测试点：`. Put tests under the domain directory documented in
`tests/kes/README.md`.

## Pull requests

- Keep KES mode differences explicit and do not claim unsupported SQL parity.
- Add a regression test before fixing a defect.
- Run unit tests, flake8, compileall, and the affected KES modes.
- Do not include generated wheels, build directories, local databases,
  credentials, or internal network details.
