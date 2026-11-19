"""Config flow for Luck Jingle printers."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.components import bluetooth
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.selector import (
    BooleanSelector,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .const import (
    BLUETOOTH_ADAPTER_AUTO,
    CONF_ADDRESS,
    CONF_BLUETOOTH_ADAPTER,
    CONF_ENABLE_NETWORK_PRINT,
    CONF_MODEL,
    CONF_NAME,
    DOMAIN,
)
from .discovery import (
    MODEL_LPC50,
    SUPPORTED_MODELS,
    adapter_sources,
    matches_model,
    printer_display_name,
)

ADVERTISEMENT_TIMEOUT = 15
MODEL_MATCHERS = {
    MODEL_LPC50: {"local_name": "LPC50_*", "connectable": True},
}


def _bluetooth_adapter_selector(sources: list[str]) -> SelectSelector:
    """Create a selector for automatic or source-specific Bluetooth."""
    return SelectSelector(
        SelectSelectorConfig(
            options=[
                SelectOptionDict(value=BLUETOOTH_ADAPTER_AUTO, label="Automatic"),
                *[
                    SelectOptionDict(value=source, label=source)
                    for source in sources
                ],
            ],
            mode=SelectSelectorMode.DROPDOWN,
        )
    )


class LuckJingleConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Configure a Luck Jingle BLE printer."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Create the options flow for an existing printer entry."""
        return LuckJingleOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Ask for the printer model and discover it over BLE."""
        errors: dict[str, str] = {}
        if user_input is not None:
            model = user_input[CONF_MODEL]
            enable_network_print = user_input[CONF_ENABLE_NETWORK_PRINT]
            devices = self._discovered_devices(model)
            if not devices:
                try:
                    device = await bluetooth.async_process_advertisements(
                        self.hass,
                        lambda info: matches_model(info.name, model),
                        MODEL_MATCHERS[model],
                        bluetooth.BluetoothScanningMode.ACTIVE,
                        ADVERTISEMENT_TIMEOUT,
                    )
                except TimeoutError:
                    errors["base"] = "printer_not_found"
                else:
                    devices = self._discovered_devices(model)
                    if not devices:
                        devices = [device]

            self._model = model
            self._enable_network_print = enable_network_print
            if len(devices) == 1:
                self._printer_address = devices[0].address
                self._printer_name = printer_display_name(devices[0].name, model)
                return await self.async_step_select_adapter()

            if len(devices) > 1:
                self._devices = {
                    info.address: printer_display_name(info.name, model)
                    for info in devices
                }
                return await self.async_step_select_device()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_MODEL): SelectSelector(
                        SelectSelectorConfig(
                            options=[
                                SelectOptionDict(value=model, label=model_name)
                                for model, model_name in SUPPORTED_MODELS.items()
                            ],
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    ),
                    vol.Required(
                        CONF_ENABLE_NETWORK_PRINT, default=False
                    ): BooleanSelector(),
                }
            ),
            errors=errors,
        )

    async def async_step_select_device(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Select a device when multiple printers of the model are visible."""
        errors: dict[str, str] = {}
        if user_input is not None:
            address = user_input[CONF_ADDRESS]
            if address in self._devices:
                self._printer_address = address
                self._printer_name = self._devices[address]
                return await self.async_step_select_adapter()
            errors["base"] = "printer_not_found"

        return self.async_show_form(
            step_id="select_device",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ADDRESS): vol.In(
                        {
                            address: f"{name} ({address})"
                            for address, name in self._devices.items()
                        }
                    )
                }
            ),
            errors=errors,
        )

    async def async_step_select_adapter(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Select which Home Assistant Bluetooth scanner should connect."""
        sources = _adapter_sources_for_address(self.hass, self._printer_address)
        options = [BLUETOOTH_ADAPTER_AUTO, *sources]
        errors: dict[str, str] = {}
        if user_input is not None:
            adapter = user_input[CONF_BLUETOOTH_ADAPTER]
            if adapter not in options:
                errors["base"] = "bluetooth_adapter_not_found"
            else:
                return await self._async_create_printer_entry(
                    self._model,
                    self._printer_address,
                    self._printer_name,
                    self._enable_network_print,
                    adapter,
                )

        return self.async_show_form(
            step_id="select_adapter",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_BLUETOOTH_ADAPTER,
                        default=BLUETOOTH_ADAPTER_AUTO,
                    ): _bluetooth_adapter_selector(sources)
                }
            ),
            errors=errors,
        )

    def _discovered_devices(
        self, model: str
    ) -> list[bluetooth.BluetoothServiceInfoBleak]:
        """Return visible BLE printers matching a selected model."""
        devices: dict[str, bluetooth.BluetoothServiceInfoBleak] = {}
        for info in bluetooth.async_discovered_service_info(
            self.hass, connectable=True
        ):
            if matches_model(info.name, model):
                devices.setdefault(info.address, info)
        return list(devices.values())

    async def _async_create_printer_entry(
        self,
        model: str,
        address: str,
        advertisement_name: str | None,
        enable_network_print: bool,
        bluetooth_adapter: str,
    ) -> config_entries.FlowResult:
        """Create an entry for a discovered printer."""
        name = printer_display_name(advertisement_name, model)
        await self.async_set_unique_id(address.casefold())
        self._abort_if_unique_id_configured()
        return self.async_create_entry(
            title=name,
            data={
                CONF_ADDRESS: address,
                CONF_BLUETOOTH_ADAPTER: bluetooth_adapter,
                CONF_ENABLE_NETWORK_PRINT: enable_network_print,
                CONF_MODEL: model,
                CONF_NAME: name,
            },
        )


def _adapter_sources_for_address(hass: HomeAssistant, address: str) -> list[str]:
    """Return Home Assistant Bluetooth sources currently seeing a printer."""
    return adapter_sources(
        bluetooth.async_scanner_devices_by_address(
            hass,
            address,
            connectable=True,
        )
    )


class LuckJingleOptionsFlow(config_entries.OptionsFlow):
    """Configure network printing for an existing printer entry."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Configure the network print relay and Bluetooth adapter."""
        address = self.config_entry.data[CONF_ADDRESS]
        sources = _adapter_sources_for_address(self.hass, address)
        enabled = self.config_entry.options.get(
            CONF_ENABLE_NETWORK_PRINT,
            self.config_entry.data.get(CONF_ENABLE_NETWORK_PRINT, False),
        )
        selected_adapter = self.config_entry.options.get(
            CONF_BLUETOOTH_ADAPTER,
            self.config_entry.data.get(
                CONF_BLUETOOTH_ADAPTER, BLUETOOTH_ADAPTER_AUTO
            ),
        )
        if (
            selected_adapter != BLUETOOTH_ADAPTER_AUTO
            and selected_adapter not in sources
        ):
            sources.append(selected_adapter)
            sources.sort()
        adapter_values = {BLUETOOTH_ADAPTER_AUTO, *sources}
        errors: dict[str, str] = {}
        if user_input is not None:
            if user_input[CONF_BLUETOOTH_ADAPTER] not in adapter_values:
                errors["base"] = "bluetooth_adapter_not_found"
            else:
                return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_BLUETOOTH_ADAPTER,
                        default=selected_adapter,
                    ): _bluetooth_adapter_selector(sources),
                    vol.Required(
                        CONF_ENABLE_NETWORK_PRINT,
                        default=enabled,
                    ): BooleanSelector(),
                }
            ),
            errors=errors,
        )

