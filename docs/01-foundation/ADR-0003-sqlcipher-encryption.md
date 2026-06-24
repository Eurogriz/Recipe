# ADR-0003: SQLCipher 4 Encryption

**Status:** Accepted
**Date:** 2026-06-24
**Deciders:** Архитектор, Security Lead

---

## Context

The application handles proprietary recipe data — intellectual property of the company. The local SQLite database must be encrypted at rest to protect:

- Confidential formulation details
- Source citations (some may be licensed material)
- User credentials (password hashes)
- Audit log

We need to choose between:
- **Option A:** SQLCipher 4 (AES-256, drop-in SQLite replacement)
- **Option B:** Application-level encryption (encrypt individual fields)
- **Option C:** Encrypted filesystem (e.g., VeraCrypt container)
- **Option D:** OS-level encryption (BitLocker on Windows)

## Decision

**SQLCipher 4 with AES-256, key derived from user passphrase via Argon2id.**

## Rationale

1. **Drop-in SQLite replacement:** SQLCipher 4 is API-compatible with SQLite 3. No code changes to SQLAlchemy.

2. **AES-256 with HMAC-SHA512:** Industry-standard encryption with authenticated encryption.

3. **Performance:** < 5% overhead compared to plaintext SQLite for typical workloads.

4. **Portable across Windows machines:** Works on any Windows 10/11 without additional drivers.

5. **Key derivation:** Argon2id (OWASP-recommended) for converting user passphrase to 256-bit encryption key.

6. **Audit-friendly:** Single encrypted file is easy to back up, version, and audit.

## Encryption Configuration

```sql
PRAGMA cipher_page_size = 4096;
PRAGMA kdf_iter = 256000;  -- PBKDF2 iterations (SQLCipher 4 default)
PRAGMA cipher_hmac_algorithm = HMAC_SHA512;
PRAGMA cipher_kdf_algorithm = PBKDF2_HMAC_SHA512;
PRAGMA cipher_use_hmac = ON;  -- authenticated encryption
PRAGMA key = "x'<64-hex-chars>'";  -- 256-bit key
```

## Key Derivation

```python
# Argon2id (OWASP-recommended parameters)
from argon2.low_level import hash_secret_raw, Type

raw_key = hash_secret_raw(
    secret=passphrase.encode("utf-8"),
    salt=salt,                # 16+ bytes, randomly generated per install
    time_cost=3,              # iterations
    memory_cost=65536,        # 64 MiB
    parallelism=4,
    hash_len=32,              # 256-bit output
    type=Type.ID,             # Argon2id (hybrid)
)
```

## Consequences

### Positive
- Strong encryption at rest
- Single-file portability
- Performance acceptable for desktop app
- No external drivers needed

### Negative (mitigated)
- **Passphrase management:** User must remember passphrase; we cannot recover it
  - **Mitigation:** Clear warnings in UI; offer password reset that creates new DB and re-imports data
- **Key derivation cost:** Argon2id takes ~1-2 seconds per session
  - **Mitigation:** Acceptable for desktop login (one-time cost)
- **Backup format:** Encrypted file is incompatible with standard SQLite tools
  - **Mitigation:** Document backup procedure; provide utility to decrypt for migration

## Security Considerations

1. **Salt:** Must be cryptographically random, ≥16 bytes, stored separately from encrypted DB
2. **Passphrase strength:** Enforce minimum 12 characters with mixed case + digits + symbols
3. **Memory:** Encryption key held in memory during session; cleared on logout
4. **Audit log:** All access events (login, key derivation, failed attempts) logged

## References

- SQLCipher 4 docs: https://www.zetetic.net/sqlcipher/
- Argon2 RFC: https://datatracker.ietf.org/doc/html/rfc9106
- OWASP Password Storage Cheat Sheet: https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html
- python-argon2: https://argon2-cffi.readthedocs.io/
