"""Parsing helpers for Luck Jingle printer QR labels."""

from __future__ import annotations

import re

BLUETOOTH_ADDRESS_PATTERN = re.compile(r"(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}\Z")
PRINTER_NAME_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,62}\Z")


def is_bluetooth_address(value: str) -> bool:
    """Return whether a value is a colon-separated Bluetooth address."""
    return BLUETOOTH_ADDRESS_PATTERN.fullmatch(value) is not None


def parse_pairing_qr(value: str) -> tuple[str, str] | None:
    """Parse a printer label payload in ``name?address`` format."""
    if len(value) > 128 or value.count("?") != 1:
        return None

    name, address = value.split("?", 1)
    if not PRINTER_NAME_PATTERN.fullmatch(name) or not is_bluetooth_address(address):
        return None

    return name, address.upper()


def matches_printer_name(advertisement_name: str | None, printer_name: str) -> bool:
    """Match a BLE advertisement to the base name printed in the pairing QR."""
    return advertisement_name == printer_name or (
        advertisement_name is not None
        and advertisement_name.startswith(f"{printer_name}_")
    )
