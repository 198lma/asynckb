Releasing asyncpg-kes
=====================

The authoritative release process is documented in ``docs/DELIVERY.md``.

A release tag must exactly match ``asyncpg/_version.py``.  Pushing the tag
starts ``.github/workflows/release.yml``, which builds the source archive and
platform wheels, generates ``SHA256SUMS``, and creates the GitHub Release.

Run the protected ``KES Integration`` workflow for all three compatibility
modes before creating the tag.  Never place KES credentials in the tag,
release notes, workflow file, or repository variables.
