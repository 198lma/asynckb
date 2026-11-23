# Upstream provenance

Independent delivery repository: https://github.com/198lma/asynckb

`asynckb` is derived from asyncpg 0.31.0, maintained by the asyncpg
authors and contributors and distributed under the Apache License 2.0.

The original Apache license text and author attribution are retained in
`LICENSE` and `AUTHORS`. `NOTICE` identifies this independent derivative and
the PSF-2.0 and 0BSD components whose license texts are in `LICENSES/`.
These files are included in both source and wheel distributions.
The combined package metadata uses `Apache-2.0 AND PSF-2.0 AND 0BSD`;
each component retains its applicable license, not a choice of licenses.
KES-specific changes are documented in `CHANGELOG.md`,
`README.rst`, and `docs/asyncpg-KES三模式适配架构总结.md`.

The `asynckb/pgproto` source is vendored in this repository so source archives
and GitHub builds are self-contained. It remains upstream asyncpg support code
and is not maintained as a separate Git submodule in this fork.

Upstream project: https://github.com/MagicStack/asyncpg

This project is an independent compatibility adaptation. It is not an
official release of MagicStack or the KingbaseES vendor.

Renaming the package does not permit replacing upstream copyright notices.
Retain legal attribution in source headers and mark modified upstream files
prominently. `NOTICE` and version-control history do not replace the
per-file requirement in Apache License 2.0 Section 4(b). Release owners must
review all modified and renamed upstream files before publication.
See `docs/DELIVERY.md` for the redistribution and TestPyPI release checklist.
