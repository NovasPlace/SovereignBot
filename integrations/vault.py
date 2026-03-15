"""Sovereign — Integrations: Credential vault (PostgreSQL backend).

Stores AES-256-GCM encrypted credentials in PostgreSQL.
Encryption key is derived from a user passphrase using PBKDF2-SHA256.
Skills NEVER see credentials directly — Sovereign's integration layer
injects them at call time only.

Schema: vault table in the sovereign database.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import threading
from typing import Optional

import psycopg2

log = logging.getLogger("sovereign.integrations.vault")

try:
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    _CRYPTO_AVAILABLE = True
except ImportError:
    _CRYPTO_AVAILABLE = False
    log.warning("cryptography not installed — vault encryption disabled")

_DATABASE_URL = os.environ.get(
    "SOVEREIGN_DATABASE_URL",
    "postgresql:///sovereign",  # Unix socket — peer auth
)

_PBKDF2_ITERATIONS = 260_000
_SALT_ENV = "SOVEREIGN_VAULT_SALT"

_DDL = """
CREATE TABLE IF NOT EXISTS vault (
    key         TEXT PRIMARY KEY,
    value_enc   BYTEA NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


class VaultLocked(Exception):
    pass


class VaultError(Exception):
    pass


class CredentialVault:
    """AES-256-GCM encrypted credential store backed by PostgreSQL.

    unlock(passphrase) must be called before any read/write.
    Skills cannot call unlock() — only daemon.py does.
    """

    def __init__(self, database_url: str = _DATABASE_URL) -> None:
        self._dsn = database_url
        self._fernet: Optional[object] = None
        self._lock = threading.Lock()
        self._init_schema()
        log.info("CredentialVault initialized (PostgreSQL)")

    def _connect(self):
        conn = psycopg2.connect(self._dsn)
        conn.autocommit = True
        return conn

    def _init_schema(self) -> None:
        conn = self._connect()
        with conn.cursor() as cur:
            cur.execute(_DDL)
        conn.close()

    def unlock(self, passphrase: str) -> None:
        """Derive encryption key from passphrase. Must be called at daemon start."""
        if not _CRYPTO_AVAILABLE:
            log.warning("Vault unlock skipped — cryptography library not available")
            return

        salt_hex = os.environ.get(_SALT_ENV, "")
        if salt_hex:
            salt = bytes.fromhex(salt_hex)
        else:
            # Generate and persist salt in DB config
            salt = os.urandom(32)
            conn = self._connect()
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO config (key, value) VALUES (%s, %s)
                    ON CONFLICT (key) DO NOTHING
                """, ("vault_salt", json.dumps(salt.hex())))
                cur.execute("SELECT value FROM config WHERE key = 'vault_salt'")
                row = cur.fetchone()
                if row:
                    # psycopg2 returns JSONB as native Python type, not JSON string
                    raw = row[0]
                    salt = bytes.fromhex(raw if isinstance(raw, str) else str(raw))
            conn.close()

        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=_PBKDF2_ITERATIONS,
        )
        key = base64.urlsafe_b64encode(kdf.derive(passphrase.encode()))
        self._fernet = Fernet(key)
        log.info("Vault unlocked")

    def lock(self) -> None:
        self._fernet = None
        log.info("Vault locked")

    def set(self, key: str, value: str) -> None:
        """Encrypt and store a credential."""
        if not self._fernet:
            raise VaultLocked("Vault is locked — call unlock() first")
        encrypted = self._fernet.encrypt(value.encode())
        conn = self._connect()
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO vault (key, value_enc)
                VALUES (%s, %s)
                ON CONFLICT (key) DO UPDATE SET
                    value_enc  = EXCLUDED.value_enc,
                    updated_at = now()
            """, (key, encrypted))
        conn.close()

    def get(self, key: str) -> Optional[str]:
        """Decrypt and return a credential. Returns None if not found."""
        if not self._fernet:
            raise VaultLocked("Vault is locked — call unlock() first")
        conn = self._connect()
        with conn.cursor() as cur:
            cur.execute("SELECT value_enc FROM vault WHERE key = %s", (key,))
            row = cur.fetchone()
        conn.close()
        if not row:
            return None
        try:
            return self._fernet.decrypt(bytes(row[0])).decode()
        except Exception as e:
            raise VaultError(f"Decryption failed for key '{key}': {e}") from e

    def delete(self, key: str) -> None:
        conn = self._connect()
        with conn.cursor() as cur:
            cur.execute("DELETE FROM vault WHERE key = %s", (key,))
        conn.close()

    def list_keys(self) -> list[str]:
        """Return all stored credential keys (not values)."""
        conn = self._connect()
        with conn.cursor() as cur:
            cur.execute("SELECT key FROM vault ORDER BY key")
            rows = cur.fetchall()
        conn.close()
        return [r[0] for r in rows]


_vault: Optional[CredentialVault] = None
_vault_lock = threading.Lock()


def get_vault(database_url: str = _DATABASE_URL) -> CredentialVault:
    global _vault
    if _vault is None:
        with _vault_lock:
            if _vault is None:
                _vault = CredentialVault(database_url)
    return _vault
