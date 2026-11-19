"""Binary sensors for Luck Jingle printers."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
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
    """Set up the network print relay status entity when enabled."""
    printer: LuckJinglePrinter = hass.data[DOMAIN][entry.entry_id]
    if printer.network_print_enabled:
        async_add_entities([LuckJingleNetworkPrintSensor(entry)])


class LuckJingleNetworkPrintSensor(BinarySensorEntity):
    """Show whether the authenticated network print relay is enabled."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_has_entity_name = True
    _attr_is_on = True
    _attr_translation_key = "network_print"

    def __init__(self, entry: ConfigEntry) -> None:
        """Initialize the relay status entity."""
        self._entry_id = entry.entry_id
        self._attr_unique_id = f"{entry.entry_id}_network_print"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.data[CONF_NAME],
            manufacturer="Luck Jingle",
            model=SUPPORTED_MODELS.get(
                entry.data.get(CONF_MODEL), "BLE thermal printer"
            ),
            connections={("bluetooth", entry.data[CONF_ADDRESS].casefold())},
        )

    @property
    def extra_state_attributes(self) -> dict[str, str]:
        """Expose the entry ID required by direct HTTP clients."""
        return {"config_entry_id": self._entry_id}
