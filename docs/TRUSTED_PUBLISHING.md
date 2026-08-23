# PyPI trusted publishing

The repository-side identity is intentionally narrow:

- PyPI project: `ragproof-cli`
- GitHub owner: `however-yir`
- Repository: `ragproof`
- Workflow: `release.yml`
- GitHub environment: `pypi`

The release workflow requests `id-token: write` only in the publish job and uses the official PyPA publishing Action pinned to a reviewed commit SHA. It does not store a PyPI API token.

To finish the one-time PyPI account binding, create a pending publisher for the values above at <https://pypi.org/manage/account/publishing/>. After the publisher is visible in PyPI, set the repository Actions variable `RAGPROOF_PYPI_PUBLISH` to `true`. Do not enable the variable before the PyPI binding exists: an otherwise valid release would fail during publication.

For an existing project, configure the same values on the project's Publishing page instead of creating a pending publisher.
