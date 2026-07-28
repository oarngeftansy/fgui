from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from figma_to_fgui.figma_pairing import PairingError, PairingStore
from figma_to_fgui.service_contracts import PluginPrincipal


class FakeClock:
    def __init__(self) -> None:
        self.now = datetime(2026, 7, 28, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **delta: int) -> None:
        self.now += timedelta(**delta)


def test_pairing_code_is_single_use_and_expires(tmp_path: Path) -> None:
    clock = FakeClock()
    store = PairingStore(tmp_path / "pairing.db", b"s" * 32, clock)
    store.initialize()

    issued = store.create_code()
    first = store.exchange(issued.code, "Figma browser")
    assert first.credential

    with pytest.raises(PairingError, match="pairing_code_invalid"):
        store.exchange(issued.code, "Repeated device")

    expired = store.create_code()
    clock.advance(minutes=11)
    with pytest.raises(PairingError, match="pairing_code_expired"):
        store.exchange(expired.code, "Expired device")


def test_pairing_store_does_not_disclose_secrets_and_revocation_is_immediate(tmp_path: Path) -> None:
    clock = FakeClock()
    database = tmp_path / "pairing.db"
    store = PairingStore(database, b"s" * 32, clock)
    store.initialize()

    issued = store.create_code()
    exchanged = store.exchange(issued.code, "Figma desktop")

    stored = database.read_bytes()
    assert issued.code.encode() not in stored
    assert exchanged.credential.encode() not in stored
    device = store.list_devices()[0]
    assert set(device.model_dump()) == {"version", "device_id", "device_name", "created_at", "revoked_at"}
    assert store.authenticate(exchanged.credential) == PluginPrincipal(device_id=device.device_id)

    store.revoke(device.device_id)
    with pytest.raises(PairingError, match="plugin_credential_revoked"):
        store.authenticate(exchanged.credential)


def test_five_invalid_exchanges_are_rate_limited_without_creating_a_device(tmp_path: Path) -> None:
    store = PairingStore(tmp_path / "pairing.db", b"s" * 32, FakeClock())
    store.initialize()

    for _ in range(4):
        with pytest.raises(PairingError, match="pairing_code_invalid"):
            store.exchange("not-a-code", "Figma desktop")
    with pytest.raises(PairingError, match="pairing_rate_limited"):
        store.exchange("not-a-code", "Figma desktop")

    assert store.list_devices() == ()
