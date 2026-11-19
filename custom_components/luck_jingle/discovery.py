"""Printer model discovery helpers."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol, TypeVar

MODEL_LPC50 = "lpc50"
SUPPORTED_MODELS = {
    MODEL_LPC50: "LPC50 (ORICO C50)",
}

_BluetoothDevice = TypeVar("_BluetoothDevice", covariant=True)


class _BluetoothScanner(Protocol):
    """The scanner attributes used by adapter selection."""

    @property
    def source(self) -> str: ...

    @property
    def name(self) -> str: ...

    @property
    def adapter(self) -> str: ...


class _BluetoothScannerDevice(Protocol[_BluetoothDevice]):
    """The device fields exposed by Home Assistant's Bluetooth manager."""

    @property
    def scanner(self) -> _BluetoothScanner: ...

    @property
    def ble_device(self) -> _BluetoothDevice: ...


def adapter_options(
    scanner_devices: Iterable[_BluetoothScannerDevice[object]],
) -> list[tuple[str, str]]:
    """Return source identifiers with friendly names for scanners seeing a device."""
    options: dict[str, str] = {}
    for device in scanner_devices:
        scanner = device.scanner
        name = scanner.name or scanner.adapter or scanner.source
        adapter = (
            f" ({scanner.adapter})"
            if scanner.adapter and scanner.adapter != name
            else ""
        )
        options[scanner.source] = (
            f"{name}{adapter} - {scanner.source}"
        )
    return sorted(options.items())


def ble_device_for_source(
    scanner_devices: Iterable[_BluetoothScannerDevice[_BluetoothDevice]],
    source: str,
) -> _BluetoothDevice | None:
    """Return the device discovered by the selected Bluetooth source."""
    return next(
        (
            device.ble_device
            for device in scanner_devices
            if device.scanner.source == source
        ),
        None,
    )


def scanner_devices_in_connection_order(
    scanner_devices: Iterable[_BluetoothScannerDevice[_BluetoothDevice]],
    preferred_source: str | None,
) -> list[_BluetoothScannerDevice[_BluetoothDevice]]:
    """Put the preferred scanner first without discarding other BLE paths."""
    devices = list(scanner_devices)
    if preferred_source is None:
        return devices
    return sorted(
        devices,
        key=lambda device: device.scanner.source != preferred_source,
    )


def matches_model(advertisement_name: str | None, model: str) -> bool:
    """Return whether a BLE advertisement belongs to a supported model."""
    if model == MODEL_LPC50:
        return advertisement_name is not None and advertisement_name.startswith(
            "LPC50_"
        )
    return False


def printer_display_name(advertisement_name: str | None, model: str) -> str:
    """Build a friendly name from an advertisement and model."""
    if advertisement_name:
        return advertisement_name.removesuffix("_BLE")
    return SUPPORTED_MODELS[model]
