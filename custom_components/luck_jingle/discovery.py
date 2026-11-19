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


class _BluetoothScannerDevice(Protocol[_BluetoothDevice]):
    """The device fields exposed by Home Assistant's Bluetooth manager."""

    @property
    def scanner(self) -> _BluetoothScanner: ...

    @property
    def ble_device(self) -> _BluetoothDevice: ...


def adapter_sources(
    scanner_devices: Iterable[_BluetoothScannerDevice[object]],
) -> list[str]:
    """Return unique source identifiers for scanners that see a device."""
    return sorted({device.scanner.source for device in scanner_devices})


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
