"""
Password hashing and verification using passlib (bcrypt).

Why hashing is required:
- Storing plain-text passwords is a critical security risk. If the database
  is breached, attackers gain direct access to every user's password.
- Users often reuse passwords across sites, so a leak exposes them elsewhere.
- Regulations (e.g. GDPR, PCI-DSS) and best practices require that passwords
  are not stored in reversible form.

Hashing is one-way: we can verify a login attempt by hashing the submitted
password and comparing it to the stored hash, but we cannot recover the
original password from the hash. bcrypt adds a per-password salt and
configurable cost to resist brute-force and rainbow-table attacks.
"""

from __future__ import annotations

from passlib.context import CryptContext

# bcrypt: industry-standard, adaptive cost, built-in salt.
# deprecated="auto" migrates legacy hashes if you switch algorithms later.
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain_password: str) -> str:
    """
    Hash a plain-text password for storage. Never store plain_password.

    Use this when creating or updating a user (e.g. registration, password
    change). Store the return value in User.hashed_password.
    """
    return pwd_context.hash(plain_password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verify a login attempt: compare plain_password to the stored hash.

    Returns True if the password matches, False otherwise. Use this during
    login to authenticate the user before issuing a session or token.
    """
    return pwd_context.verify(plain_password, hashed_password)
