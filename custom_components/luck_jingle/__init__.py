"""Luck Jingle BLE thermal printer integration."""

from __future__ import annotations

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv

from .const import (
    CONF_ADDRESS,
    CONF_NAME,
    DOMAIN,
    PLATFORMS,
    SERVICE_PRINT_TEXT,
)
from .printer import LuckJinglePrinter

ATTR_CONFIG_ENTRY_ID = "config_entry_id"
ATTR_DENSITY = "density"
ATTR_FEED = "feed"
ATTR_TEXT = "text"
MAX_TEXT_LENGTH = 2000

PRINT_TEXT_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_TEXT): vol.All(str, vol.Length(min=1, max=MAX_TEXT_LENGTH)),
        vol.Optional(ATTR_DENSITY, default=1): vol.All(
            vol.Coerce(int), vol.Range(min=0, max=2)
        ),
        vol.Optional(ATTR_FEED, default=80): vol.All(
            vol.Coerce(int), vol.Range(min=0, max=255)
        ),
        vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
    }
)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the integration."""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a configured printer."""
    printers: dict[str, LuckJinglePrinter] = hass.data.setdefault(DOMAIN, {})
    printer = LuckJinglePrinter(
        hass,
        entry.data[CONF_ADDRESS],
        entry.data[CONF_NAME],
    )
    printers[entry.entry_id] = printer

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    if not hass.services.has_service(DOMAIN, SERVICE_PRINT_TEXT):

        async def async_print_text(call: ServiceCall) -> None:
            """Print text on the selected printer."""
            entry_id = call.data.get(ATTR_CONFIG_ENTRY_ID)
            if entry_id is None:
                if len(printers) != 1:
                    raise HomeAssistantError(
                        "Set config_entry_id when more than one Luck Jingle printer is configured"
                    )
                printer_to_use = next(iter(printers.values()))
            else:
                printer_to_use = printers.get(entry_id)
                if printer_to_use is None:
                    raise HomeAssistantError(
                        f"No Luck Jingle printer configured with entry ID {entry_id}"
                    )

            await printer_to_use.async_print_text(
                call.data[ATTR_TEXT],
                density=call.data[ATTR_DENSITY],
                feed=call.data[ATTR_FEED],
            )

        hass.services.async_register(
            DOMAIN,
            SERVICE_PRINT_TEXT,
            async_print_text,
            schema=PRINT_TEXT_SCHEMA,
        )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a configured printer."""
    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        return False

    printers: dict[str, LuckJinglePrinter] = hass.data[DOMAIN]
    printers.pop(entry.entry_id)
    if not printers:
        hass.services.async_remove(DOMAIN, SERVICE_PRINT_TEXT)
        hass.data.pop(DOMAIN)
    return True
