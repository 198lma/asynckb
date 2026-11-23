<!-- Modified for asynckb: independent distribution and KES compatibility. -->

# Changelog

All notable changes to `asynckb` are documented in this file.

## Unreleased

- Preserve upstream copyright and modified-file notices; ship Apache-2.0,
  PSF-2.0 and 0BSD texts with source and wheel distributions.
- Use the independent `198lma/asynckb` delivery repository.
- Finalize the distribution and Python import name as `asynckb` and the
  SQLAlchemy URL as `kingbase+asynckb://`.
- Rename C extension namespaces, build/test environment variables, examples,
  and delivery configuration to match the distribution name.
- Retain Python 3.9+ and the shared MySQL, Oracle, and SQL Server KES
  compatibility-mode implementation, including type/OID handling.

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

- Distribution name: `asynckb`.
- Import name: `asynckb`.
- Upstream baseline: asyncpg 0.31.0.
- SQLAlchemy URL scheme: `kingbase+asynckb`.
