"""Config flow for Luck Jingle printers."""

from __future__ import annotations

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.components import bluetooth

from .const import CONF_ADDRESS, CONF_NAME, DEFAULT_NAME, DOMAIN
from .qr import is_bluetooth_address, matches_printer_name, parse_pairing_qr

ADVERTISEMENT_TIMEOUT = 15


class LuckJingleConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Configure a Luck Jingle BLE printer."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, str] | None = None
    ) -> config_entries.FlowResult:
        """Accept a printer QR payload or a BLE address."""
        errors: dict[str, str] = {}
        if user_input is not None:
            pairing_code = user_input["pairing_code"].strip()
            display_name = user_input.get(CONF_NAME, "").strip()
            parsed_qr = parse_pairing_qr(pairing_code)
            if parsed_qr is not None:
                qr_name, _classic_address = parsed_qr
                name = display_name or qr_name
                service_info = next(
                    (
                        info
                        for info in bluetooth.async_discovered_service_info(
                            self.hass, connectable=True
                        )
                        if matches_printer_name(info.name, qr_name)
                    ),
                    None,
                )
                if service_info is None:
                    try:
                        service_info = await bluetooth.async_process_advertisements(
                            self.hass,
                            lambda info: matches_printer_name(info.name, qr_name),
                            {"local_name": f"{qr_name}*", "connectable": True},
                            bluetooth.BluetoothScanningMode.ACTIVE,
                            ADVERTISEMENT_TIMEOUT,
                        )
                    except TimeoutError:
                        errors["base"] = "printer_not_found"

                if service_info is not None:
                    address = service_info.address
                else:
                    address = ""
            elif is_bluetooth_address(pairing_code):
                address = pairing_code.upper()
                name = display_name or DEFAULT_NAME
            else:
                address = ""
                name = display_name or DEFAULT_NAME
                errors["base"] = "invalid_pairing_code"

            if address:
                await self.async_set_unique_id(address.casefold())
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=name,
                    data={CONF_ADDRESS: address, CONF_NAME: name},
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required("pairing_code"): str,
                    vol.Optional(CONF_NAME): str,
                }
            ),
            errors=errors,
        )

