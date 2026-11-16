"""Config flow for Luck Jingle printers."""

from __future__ import annotations

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.components import bluetooth
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .const import CONF_ADDRESS, CONF_MODEL, CONF_NAME, DOMAIN
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

    async def async_step_user(
        self, user_input: dict[str, str] | None = None
    ) -> config_entries.FlowResult:
        """Ask for the printer model and discover it over BLE."""
        errors: dict[str, str] = {}
        if user_input is not None:
            model = user_input[CONF_MODEL]
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
                    model, devices[0].address, devices[0].name
                )

            if len(devices) > 1:
                self._model = model
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
                    )
                }
            ),
            errors=errors,
        )

    async def async_step_select_device(
        self, user_input: dict[str, str] | None = None
    ) -> config_entries.FlowResult:
        """Select a device when multiple printers of the model are visible."""
        errors: dict[str, str] = {}
        if user_input is not None:
            address = user_input[CONF_ADDRESS]
            if address in self._devices:
                return await self._async_create_printer_entry(
                    self._model, address, self._devices[address]
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
        self, model: str, address: str, advertisement_name: str | None
    ) -> config_entries.FlowResult:
        """Create an entry for a discovered printer."""
        name = printer_display_name(advertisement_name, model)
        await self.async_set_unique_id(address.casefold())
        self._abort_if_unique_id_configured()
        return self.async_create_entry(
            title=name,
            data={CONF_ADDRESS: address, CONF_MODEL: model, CONF_NAME: name},
        )

