"""Config flow for Luck Jingle printers."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.components import bluetooth
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    BooleanSelector,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .const import (
    CONF_ADDRESS,
    CONF_ENABLE_NETWORK_PRINT,
    CONF_MODEL,
    CONF_NAME,
    DOMAIN,
)
from .discovery import (
    MODEL_LPC50,
    SUPPORTED_MODELS,
    matches_model,
    printer_display_name,
)

ADVERTISEMENT_TIMEOUT = 15
MODEL_MATCHERS = {
    MODEL_LPC50: {"local_name": "LPC50_*", "connectable": True},
}


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

            if len(devices) == 1:
                return await self._async_create_printer_entry(
                    model,
                    devices[0].address,
                    devices[0].name,
                    enable_network_print,
                )

            if len(devices) > 1:
                self._model = model
                self._enable_network_print = enable_network_print
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
                return await self._async_create_printer_entry(
                    self._model,
                    address,
                    self._devices[address],
                    self._enable_network_print,
                )
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

    def _discovered_devices(
        self, model: str
    ) -> list[bluetooth.BluetoothServiceInfoBleak]:
        """Return visible BLE printers matching a selected model."""
        return [
            info
            for info in bluetooth.async_discovered_service_info(
                self.hass, connectable=True
            )
            if matches_model(info.name, model)
        ]

    async def _async_create_printer_entry(
        self,
        model: str,
        address: str,
        advertisement_name: str | None,
        enable_network_print: bool,
    ) -> config_entries.FlowResult:
        """Create an entry for a discovered printer."""
        name = printer_display_name(advertisement_name, model)
        await self.async_set_unique_id(address.casefold())
        self._abort_if_unique_id_configured()
        return self.async_create_entry(
            title=name,
            data={
                CONF_ADDRESS: address,
                CONF_ENABLE_NETWORK_PRINT: enable_network_print,
                CONF_MODEL: model,
                CONF_NAME: name,
            },
        )


class LuckJingleOptionsFlow(config_entries.OptionsFlow):
    """Configure network printing for an existing printer entry."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Toggle the authenticated network print relay."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        enabled = self.config_entry.options.get(
            CONF_ENABLE_NETWORK_PRINT,
            self.config_entry.data.get(CONF_ENABLE_NETWORK_PRINT, False),
        )
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_ENABLE_NETWORK_PRINT,
                        default=enabled,
                    ): BooleanSelector(),
                }
            ),
        )

