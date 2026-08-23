# Releasing ragproof

## What a tag release does

Pushing a tag such as `v0.4.1` starts the Release workflow. It verifies that the tag exactly matches `project.version`, builds the source distribution and wheel, checks package metadata, smoke-tests the wheel in a clean virtual environment, generates a reproducible CycloneDX SBOM and SHA256 checksum file, creates a GitHub build-provenance attestation, extracts the matching section from `CHANGELOG.md`, and creates or updates the GitHub Release with those files attached.

The release is deliberately idempotent: rerunning it updates the notes and replaces the two distribution assets instead of creating a second release.

## Release checklist

1. Update `pyproject.toml`, `ragproof/__init__.py`, and `CHANGELOG.md` to the same version.
2. Merge the version commit into `main` only after CI is green.
3. Create and push the matching annotated tag: `git tag -a vX.Y.Z -m "ragproof X.Y.Z" && git push origin vX.Y.Z`.
4. Confirm the Release workflow attached the wheel, source distribution, SBOM, and checksum file, and rendered the intended changelog section.

## Distribution identity and PyPI safety gate

The distribution name is `ragproof-cli`; the import package and console command remain `ragproof`. The PyPI name `ragproof` belongs to an unrelated project and must never be used in installation instructions for this repository.

PyPI publication is disabled by default. Set the repository variable `RAGPROOF_PYPI_PUBLISH` to `true` only after confirming that this repository owns `ragproof-cli` and that its PyPI Trusted Publisher is bound to `.github/workflows/release.yml` with the `pypi` environment.

The exact one-time identity fields are recorded in [TRUSTED_PUBLISHING.md](TRUSTED_PUBLISHING.md).

This guard prevents a tag from attempting an unverified publication. The GitHub Release remains fully usable without PyPI: users can install directly from its tag or download the attached `ragproof_cli-*.whl` file.
