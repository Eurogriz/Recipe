# Security policy

## Supported versions

| Version | Supported |
| ------- | --------- |
| 1.1.x   | ✅ |
| 1.0.x   | ❌ (pre-headless; upgrade to 1.1) |

## Reporting a vulnerability

**Please do not open a public GitHub issue for security problems.**

Instead, email `security@formulation-workbench.local` (or open a
[private vulnerability report](https://github.com/Eurogriz/Recipe/security/advisories/new))
with:

- affected version(s);
- reproduction steps or a proof of concept;
- impact assessment (data disclosure, RCE, DoS, …);
- your contact information for follow-up.

You will receive an acknowledgement within **3 business days**. We aim to
publish a fix or mitigation within **30 days** of a confirmed report.

## Hardening baseline

- All released container images are signed via **Sigstore / cosign** (keyless).
- SBOMs in CycloneDX JSON are attached to every GitHub release.
- SLSA v1 build provenance is generated for both wheels and containers
  (`actions/attest-build-provenance`).
- Dependencies are scanned weekly by **Dependabot** and **`pip-audit`** in CI.
- Python code is linted by **Ruff** (with security rules `S…`) and audited by **Bandit**.
- The default database backend supports **SQLCipher (AES-256)** through the
  `sqlcipher` extra; keys are derived from a passphrase via **Argon2id**.
- The FastAPI facade supports **Bearer-token** authentication and is enforced
  in production by `AppSettings.enforce_production_invariants`.

## Cryptography notes

The application does not roll its own cryptography. It relies on:

- [`argon2-cffi`](https://argon2-cffi.readthedocs.io/) for KDF operations.
- [`cryptography`](https://cryptography.io/) for symmetric primitives.
- [`sqlcipher3`](https://github.com/coleifer/sqlcipher3) for at-rest encryption.
