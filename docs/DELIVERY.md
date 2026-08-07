# GitHub delivery and release

## Repository model

- Protect `main`; prohibit force pushes and require the `Regression Tests`
  check before merging.
- Use pull requests for source changes.
- Keep KES credentials in the protected GitHub Environment `kes-test`.
- Publish binary artifacts through GitHub Releases, not Git commits.

## CI layers

1. `.github/workflows/tests.yml` runs static checks and KES-independent unit
   tests on GitHub-hosted runners.
2. `.github/workflows/kes-integration.yml` runs the complete three-mode suite
   on a runner labelled `self-hosted`, `linux`, `x64`, and `kes`.
3. `.github/workflows/release.yml` validates a version tag, builds source and
   wheel distributions, generates SHA256 checksums, and creates a GitHub
   Release.

The self-hosted runner must be managed as a non-root service account, have
network access only to the test KES instances, and contain no production
credentials.

## GitHub Environment secrets

```text
ASYNCPG_KES_HOST
ASYNCPG_KES_USER
ASYNCPG_KES_PASSWORD
ASYNCPG_KES_DATABASE
ASYNCPG_KES_MYSQL_PORT
ASYNCPG_KES_ORACLE_PORT
ASYNCPG_KES_SQLSERVER_PORT
```

## Release procedure

1. Update `asyncpg/_version.py` and `CHANGELOG.md`.
2. Merge through a pull request after public CI passes.
3. Run `KES Integration` for `all` modes and retain its JUnit artifact.
4. Create and push a signed tag matching the package version:

   ```bash
   git tag -s v0.31.0.post12 -m "asyncpg-kes 0.31.0.post12"
   git push origin v0.31.0.post12
   ```

5. Verify every GitHub Release asset against `SHA256SUMS`.
6. Install a release wheel in a clean environment outside the source tree and
   run the KES acceptance suite before promoting the release.

PyPI publishing is intentionally not automatic. Configure PyPI Trusted
Publishing and a protected GitHub Environment before adding that step.
