# GitHub delivery and release

## Repository model

The delivery repository is `https://github.com/198lma/asynckb`. It was
created as a private, empty repository; creation does not upload this
checkout or publish a release. The local `asynckb` remote targets it, while
`origin` retains the old repository for reference. Do not push a release
tag until the reviewed source and workflows have been pushed to the new
repository and its CI, permissions and secrets have been configured.

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
ASYNCKB_KES_HOST
ASYNCKB_KES_USER
ASYNCKB_KES_PASSWORD
ASYNCKB_KES_DATABASE
ASYNCKB_KES_MYSQL_PORT
ASYNCKB_KES_ORACLE_PORT
ASYNCKB_KES_SQLSERVER_PORT
```

## Release procedure

1. Update `asynckb/_version.py` and `CHANGELOG.md`.
2. Merge through a pull request after public CI passes.
3. Run `KES Integration` for `all` modes and retain its JUnit artifact.
4. Create and push a signed tag matching the package version:

   ```bash
   git tag -s v0.31.0.post12 -m "asynckb 0.31.0.post12"
   git push asynckb v0.31.0.post12
   ```

5. Verify every GitHub Release asset against `SHA256SUMS`.
6. Install a release wheel in a clean environment outside the source tree and
   run the KES acceptance suite before promoting the release.

PyPI publishing is intentionally not automatic. Configure PyPI Trusted
Publishing and a protected GitHub Environment before adding that step.

## License and independent-distribution review

The distribution name, Python import namespace and extension modules are
`asynckb`; the SQLAlchemy URL is `kingbase+asynckb://...`. Upstream names in
copyright headers and license attribution must not be renamed or removed.
Protocol terms, database compatibility identifiers and upstream API names
are not release branding and must not be blindly replaced.

The upstream asyncpg 0.31.0 license is Apache-2.0. The local `LICENSE`
retains its original text and adds a clearly separate explanatory note.
The source also includes PSF-2.0 code and the 0BSD pythoncapi_compat header;
package metadata therefore uses `Apache-2.0 AND PSF-2.0 AND 0BSD`.
This expression describes bundled components; it does not relicense them.

Before any public or customer release:

1. Retain the upstream copyright notices and author attribution. Ship
   `LICENSE`, `NOTICE`, `AUTHORS`, `UPSTREAM.md`, `LICENSES/PSF-2.0.txt`
   and `LICENSES/0BSD.txt` in both the sdist and wheel. Check the built
   archives, not only the source-tree manifest.
2. Review every modified upstream file, including namespace-only renames,
   and add a prominent change notice while preserving its original legal
   header. Example: `Modified for asynckb: independent package namespace
   and KES compatibility; see CHANGELOG.md.` Use the file's comment syntax.
   For generated C, preserve generator notices and carry the attribution
   from the corresponding source. A central NOTICE or Git history alone
   does not satisfy Apache Section 4(b).
   Keep modification notices in generator templates as well, and recheck
   generated files after regeneration rather than assuming old headers
   survived.
3. Record functional changes and the upstream base version. Do not claim
   authorship of the upstream implementation or endorsement by upstream
   maintainers. Do not use upstream trademarks as release branding.
4. Confirm the legal copyright holder for project-specific changes,
   publisher account, contact details and authoritative self-hosted
   repository URL against the contract. Package metadata targets the new
   `198lma/asynckb` repository. The old CI badge was removed; add a new badge
   only after CI is running in the new repository. The existing Git remote
   alone does not establish contractual approval or copyright ownership.
   Do not invent a corporate copyright statement before ownership is
   confirmed.
5. Audit any dependencies or runtime libraries actually bundled into a
   release. This source-level notice inventory is not a complete SBOM for
   future repaired wheels, containers or offline dependency bundles.

Apache-2.0 permits modified, renamed and commercial redistribution subject
to its conditions; it does not by itself require publishing all changes
or grant trademark rights. Contractual IP and delivery obligations remain
separate. Obtain the release owner's legal approval before distribution.

## TestPyPI before production PyPI

1. Select an unused `asynckb` release version and build a clean sdist and
   platform wheels. Run `python -m twine check` against those exact files.
   Never upload stale `asyncpg` or `asynckes` artifacts from an old `dist/`.
2. Configure the separate TestPyPI account or Trusted Publisher and upload
   only the selected artifacts with
   `python -m twine upload --repository testpypi <artifact paths>`.
   Do not include tokens in scripts, source control or documentation.
3. In a clean environment outside the checkout, install the exact version
   from `https://test.pypi.org/simple/`. Install required dependencies from
   the approved production index separately; avoid mixing an untrusted
   `--extra-index-url` into the same resolution. Confirm the installed
   distribution/import identity, extension modules, license files,
   `kingbase+asynckb` entry point and three-mode acceptance results.
4. Publish the verified artifacts to production PyPI only after approval.
   TestPyPI and PyPI have separate accounts, project namespaces and release
   histories; availability on TestPyPI does not reserve the PyPI name.
   Uploaded filenames cannot be overwritten or reused, even after deletion.
   If changing an existing artifact, select a new version rather than
   attempting same-name/same-version replacement.

This checklist does not upload artifacts or establish that the final
project name, copyright owner or publisher authorization has been approved.
