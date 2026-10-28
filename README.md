# release-workflows

Reusable GitHub Actions workflows that Black Lantern Security repositories call to test, build, check and
publish releases. Callers execute this code with their own permissions and secrets, so it is held to the
same release controls as the projects it publishes.

| Workflow | Purpose |
|---|---|
| `python-tests.yml`, `python-versions.yml`, `rust-tests.yml` | Test matrices |
| `stable-guard.yml` | Checks a pull request into `stable` is release-ready: a MAJOR.MINOR.PATCH version, matching chart versions, no git dependencies |
| `release-check.yml` | Runs on `stable` only: reads the version, refuses a partly published release, checks merged-PR provenance and that the `release` environment is protected |
| `maturin-wheels.yml`, `crates.yml`, `docker.yml` | Build and publish artifacts |
| `docker-dev.yml` | `dev` channel images on GHCR (not releases) |
| `publish.yml` | Creates the tag and GitHub release with the release App, after everything is published |
| `cla-reusable.yml` | CLA check. The agreement and signatures live in [`CLA`](https://github.com/blacklanternsecurity/CLA) |

## Using a workflow

Pin a release by full commit SHA, with the version as a comment:

```yaml
jobs:
  check:
    uses: blacklanternsecurity/release-workflows/.github/workflows/release-check.yml@<full sha of the tag> # v1.0.0
```

Use the SHA of a `v*` tag of this repository, never a branch. Tags here are created only by the release
App and can't be moved or deleted, so a version comment always matches its SHA.

## How changes land

- `dev`: pull request, required tests and security checks (CodeQL, dependency review, `actionlint`,
  `zizmor`). No approval needed.
- `stable`: pull request from `dev`, approved by a code owner other than the last pusher, required checks.
  Nobody bypasses it.
- A merge to `stable` runs `release.yml`, which tags the merge commit `v<version>` from `pyproject.toml`.
  It stops twice at the `release` environment, once before checking the release credentials and once
  before publishing, and each stop needs a `bbot-leads` approval.

Versions follow semantic versioning: a change to a workflow's inputs, outputs, secrets or required
permissions that a caller must act on is a major version.

## Tests

```bash
uv run --group dev pytest
uv run --group dev actionlint
```
