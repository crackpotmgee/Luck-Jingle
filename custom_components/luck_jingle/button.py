"""Buttons for Luck Jingle printers."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_ADDRESS, CONF_MODEL, CONF_NAME, DOMAIN
from .discovery import SUPPORTED_MODELS
from .printer import LuckJinglePrinter


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the printer's test-print button."""
    printer: LuckJinglePrinter = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([LuckJingleTestButton(entry, printer)])


class LuckJingleTestButton(ButtonEntity):
    """Button that prints a test label."""

    _attr_has_entity_name = True
    _attr_translation_key = "test_print"

    def __init__(self, entry: ConfigEntry, printer: LuckJinglePrinter) -> None:
        """Initialize the button."""
        self._printer = printer
        self._attr_unique_id = f"{entry.entry_id}_test_print"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.data[CONF_NAME],
            manufacturer="Luck Jingle",
            model=SUPPORTED_MODELS.get(
                entry.data.get(CONF_MODEL), "BLE thermal printer"
            ),
            connections={("bluetooth", entry.data[CONF_ADDRESS].casefold())},
        )

    async def async_press(self) -> None:
        """Print a test label."""
        await self._printer.async_print_text("Luck Jingle\nTest print")
