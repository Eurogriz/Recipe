# CI templates

The workflow YAMLs in this directory are ready-to-use for the project but
were pushed here instead of `.github/workflows/` because Arena's
short-lived GitHub App does not carry the `workflows` permission.

## Activate them

```bash
# From the repository root, once you have push access with workflows permission:
mkdir -p .github/workflows
cp ci-templates/workflows/*.yml .github/workflows/
git add .github/workflows/*.yml
git commit -m "ci: enable CI + release workflows"
git push
```

## Contents

- `ci.yml` — pull-request / push CI:
  - Ruff (lint + format check)
  - Bandit + `pip-audit`
  - MyPy strict (non-blocking today)
  - `pytest` matrix on Python 3.10 / 3.11 / 3.12 across Ubuntu and Python 3.11
    on macOS and Windows
  - CycloneDX SBOM upload
  - Docker build + `/health` smoke test

- `release.yml` — triggered on `v*.*.*` tags:
  - Build `sdist` + `wheel` with SLSA v1 provenance attestation
  - Multi-arch (`linux/amd64`, `linux/arm64`) OCI image push to GHCR
  - Cosign keyless signing of the image
  - Container provenance attestation
  - GitHub Release with SBOM + generated notes
