"""Printer model discovery helpers."""

from __future__ import annotations

MODEL_LPC50 = "lpc50"
SUPPORTED_MODELS = {
    MODEL_LPC50: "LPC50 (ORICO C50)",
}


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
