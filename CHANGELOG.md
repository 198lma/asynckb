# Changelog

All notable changes to `asyncpg-kes` are documented in this file.

## 0.31.0.post12 - 2026-08-07

### Added

- KingbaseES MySQL, Oracle, and SQL Server compatibility modes through the
  `kes_mode` connection option.
- Dynamic KES type discovery and mode-specific codecs.
- Mode-aware transactions, prepared statement handling, COPY behavior, and
  connection pooling.
- SQLAlchemy 2.x asynchronous dialects and Alembic integration for all three
  KES compatibility modes.
- Repository-owned KES unit, integration, framework, asynchronous workflow,
  and resource-cleanup tests.
- GitHub CI, self-hosted KES regression, and tag-based release workflows.

### Verified

- KingbaseES `V009R001C010` MySQL, Oracle, and SQL Server compatibility modes.
- 355 automated test nodes with no failures or skipped tests in the recorded
  local acceptance environment.
- Strict asyncio resource checks with `ResourceWarning` and `RuntimeWarning`
  promoted to errors.

### Compatibility

- Distribution name: `asyncpg-kes`.
- Import name: `asyncpg`.
- Upstream baseline: asyncpg 0.31.0.
- `asyncpg` and `asyncpg-kes` must not be installed in the same environment.
