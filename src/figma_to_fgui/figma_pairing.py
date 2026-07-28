from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from figma_to_fgui.service_contracts import (
    FigmaDeviceView,
    PairingCodeView,
    PluginCredentialView,
    PluginPrincipal,
)

_CODE_TTL = timedelta(minutes=10)
_RATE_LIMIT_WINDOW = timedelta(minutes=10)
_RATE_LIMIT_ATTEMPTS = 5


class PairingError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _digest(secret: bytes, purpose: bytes, value: str) -> str:
    return hmac.new(secret, purpose + b"\0" + value.encode("utf-8"), hashlib.sha256).hexdigest()


class PairingStore:
    def __init__(self, db_path: Path, secret: bytes, clock: Callable[[], datetime]) -> None:
        self._db_path = db_path
        self._secret = secret
        self._clock = clock

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def initialize(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS pairing_codes (
                    code_digest TEXT PRIMARY KEY,
                    expires_at REAL NOT NULL,
                    consumed_at REAL
                );
                CREATE TABLE IF NOT EXISTS plugin_devices (
                    device_id TEXT PRIMARY KEY,
                    device_name TEXT NOT NULL,
                    credential_digest TEXT NOT NULL UNIQUE,
                    created_at REAL NOT NULL,
                    revoked_at REAL
                );
                CREATE TABLE IF NOT EXISTS pairing_failures (
                    scope TEXT PRIMARY KEY,
                    window_started_at REAL NOT NULL,
                    attempts INTEGER NOT NULL CHECK(attempts BETWEEN 0 AND 5)
                );
                """
            )

    def _now(self) -> datetime:
        now = self._clock()
        return now if now.tzinfo is not None else now.replace(tzinfo=UTC)

    @staticmethod
    def _timestamp(value: datetime) -> float:
        return value.timestamp()

    @staticmethod
    def _datetime(value: float | None) -> datetime | None:
        return None if value is None else datetime.fromtimestamp(value, tz=UTC)

    def create_code(self) -> PairingCodeView:
        now = self._now()
        expires_at = now + _CODE_TTL
        with self._connect() as connection:
            for _ in range(3):
                code = f"{secrets.randbelow(1_000_000):06d}"
                try:
                    connection.execute(
                        "INSERT INTO pairing_codes(code_digest, expires_at) VALUES (?, ?)",
                        (_digest(self._secret, b"pairing-code", code), self._timestamp(expires_at)),
                    )
                except sqlite3.IntegrityError:
                    continue
                return PairingCodeView(code=code, expires_at=expires_at)
        raise RuntimeError("unable to issue pairing code")

    def _invalid_attempt(self, connection: sqlite3.Connection, now: datetime) -> PairingError:
        now_value = self._timestamp(now)
        row = connection.execute(
            "SELECT window_started_at, attempts FROM pairing_failures WHERE scope = 'exchange'"
        ).fetchone()
        if row is None or now_value - row["window_started_at"] >= _RATE_LIMIT_WINDOW.total_seconds():
            attempts = 1
            window_started_at = now_value
        else:
            attempts = min(_RATE_LIMIT_ATTEMPTS, row["attempts"] + 1)
            window_started_at = row["window_started_at"]
        connection.execute(
            "INSERT INTO pairing_failures(scope, window_started_at, attempts) VALUES ('exchange', ?, ?) "
            "ON CONFLICT(scope) DO UPDATE SET window_started_at = excluded.window_started_at, "
            "attempts = excluded.attempts",
            (window_started_at, attempts),
        )
        connection.commit()
        return PairingError(
            "pairing_rate_limited" if attempts >= _RATE_LIMIT_ATTEMPTS else "pairing_code_invalid"
        )

    def _device_view(self, row: sqlite3.Row) -> FigmaDeviceView:
        return FigmaDeviceView(
            device_id=row["device_id"],
            device_name=row["device_name"],
            created_at=datetime.fromtimestamp(row["created_at"], tz=UTC),
            revoked_at=self._datetime(row["revoked_at"]),
        )

    def exchange(self, code: str, device_name: str) -> PluginCredentialView:
        now = self._now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if len(code) != 6 or not code.isascii() or not code.isdigit():
                raise self._invalid_attempt(connection, now)
            row = connection.execute(
                "SELECT expires_at, consumed_at FROM pairing_codes WHERE code_digest = ?",
                (_digest(self._secret, b"pairing-code", code),),
            ).fetchone()
            if row is None or row["consumed_at"] is not None:
                raise self._invalid_attempt(connection, now)
            if self._timestamp(now) >= row["expires_at"]:
                raise PairingError("pairing_code_expired")
            device_id = uuid.uuid4().hex
            credential = secrets.token_urlsafe(32)
            connection.execute(
                "UPDATE pairing_codes SET consumed_at = ? WHERE code_digest = ?",
                (self._timestamp(now), _digest(self._secret, b"pairing-code", code)),
            )
            connection.execute(
                "INSERT INTO plugin_devices(device_id, device_name, credential_digest, created_at) "
                "VALUES (?, ?, ?, ?)",
                (
                    device_id,
                    device_name,
                    _digest(self._secret, b"plugin-credential", credential),
                    self._timestamp(now),
                ),
            )
        return PluginCredentialView(
            credential=credential,
            device=FigmaDeviceView(
                device_id=device_id,
                device_name=device_name,
                created_at=now,
            ),
        )

    def list_devices(self) -> tuple[FigmaDeviceView, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT device_id, device_name, created_at, revoked_at FROM plugin_devices "
                "WHERE revoked_at IS NULL ORDER BY created_at, device_id"
            ).fetchall()
        return tuple(self._device_view(row) for row in rows)

    def revoke(self, device_id: str) -> FigmaDeviceView:
        now = self._now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT device_id, device_name, created_at, revoked_at FROM plugin_devices WHERE device_id = ?",
                (device_id,),
            ).fetchone()
            if row is None:
                raise PairingError("plugin_credential_invalid")
            if row["revoked_at"] is None:
                connection.execute(
                    "UPDATE plugin_devices SET revoked_at = ? WHERE device_id = ?",
                    (self._timestamp(now), device_id),
                )
                row = connection.execute(
                    "SELECT device_id, device_name, created_at, revoked_at FROM plugin_devices "
                    "WHERE device_id = ?",
                    (device_id,),
                ).fetchone()
        assert row is not None
        return self._device_view(row)

    def authenticate(self, credential: str) -> PluginPrincipal:
        credential_digest = _digest(self._secret, b"plugin-credential", credential)
        with self._connect() as connection:
            row = connection.execute(
                "SELECT device_id, credential_digest, revoked_at FROM plugin_devices "
                "WHERE credential_digest = ?",
                (credential_digest,),
            ).fetchone()
        if row is None or not hmac.compare_digest(row["credential_digest"], credential_digest):
            raise PairingError("plugin_credential_invalid")
        if row["revoked_at"] is not None:
            raise PairingError("plugin_credential_revoked")
        return PluginPrincipal(device_id=row["device_id"])
