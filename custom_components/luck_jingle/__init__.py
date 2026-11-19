"""Luck Jingle BLE thermal printer integration."""

from __future__ import annotations

import json
from typing import Any

import voluptuous as vol
from aiohttp import web
from aiohttp.client_exceptions import ContentTypeError

from homeassistant.components.http import HomeAssistantView
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv

from .const import (
    BLUETOOTH_ADAPTER_AUTO,
    CONF_ADDRESS,
    CONF_BLUETOOTH_ADAPTER,
    CONF_ENABLE_NETWORK_PRINT,
    CONF_NAME,
    DOMAIN,
    PLATFORMS,
    SERVICE_PRINT_TEXT,
)
from .printer import LuckJinglePrinter
from .protocol import MAX_DOCUMENT_BYTES, render_document

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

PRINT_DOCUMENT_OPTIONS_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_DENSITY, default=1): vol.All(
            vol.Coerce(int), vol.Range(min=0, max=2)
        ),
        vol.Optional(ATTR_FEED, default=80): vol.All(
            vol.Coerce(int), vol.Range(min=0, max=255)
        ),
    }
)


class NetworkPrintView(HomeAssistantView):
    """Authenticated HTTP endpoint for network print clients."""

    url = "/api/luck_jingle/print/{entry_id}"
    name = "api:luck_jingle:print"
    requires_auth = True

    async def post(
        self, request: web.Request, entry_id: str
    ) -> web.Response:
        """Print a text job for the selected printer."""
        hass = request.app["hass"]
        printer: LuckJinglePrinter | None = hass.data.get(DOMAIN, {}).get(entry_id)
        if printer is None or not printer.network_print_enabled:
            return self.json_message(
                "Network printing is not enabled for this printer",
                status_code=404,
            )

        if request.content_type == "application/json":
            try:
                data = PRINT_TEXT_SCHEMA(await request.json())
            except (
                json.JSONDecodeError,
                UnicodeDecodeError,
                ContentTypeError,
            ):
                return self.json_message(
                    "The request body must be valid JSON",
                    status_code=400,
                )
            except vol.Invalid as err:
                return self.json_message(str(err), status_code=400)

            data[ATTR_CONFIG_ENTRY_ID] = entry_id
            try:
                await _async_print_text(hass, data)
            except HomeAssistantError as err:
                return self.json_message(str(err), status_code=502)
            return self.json({"status": "printed"})

        content_type = request.content_type
        if (
            content_type != "application/pdf"
            and content_type != "application/octet-stream"
            and not content_type.startswith("image/")
        ):
            return self.json_message(
                "Content-Type must be application/pdf, an image format, or "
                "application/octet-stream",
                status_code=415,
            )

        if (
            request.content_length is not None
            and request.content_length > MAX_DOCUMENT_BYTES
        ):
            return self.json_message(
                f"Documents must be at most {MAX_DOCUMENT_BYTES} bytes",
                status_code=413,
            )
        payload = bytearray()
        async for chunk in request.content.iter_chunked(64 * 1024):
            payload.extend(chunk)
            if len(payload) > MAX_DOCUMENT_BYTES:
                return self.json_message(
                    f"Documents must be at most {MAX_DOCUMENT_BYTES} bytes",
                    status_code=413,
                )
        try:
            options = PRINT_DOCUMENT_OPTIONS_SCHEMA(request.query)
        except vol.Invalid as err:
            return self.json_message(str(err), status_code=400)

        try:
            bitmaps = await hass.async_add_executor_job(
                render_document,
                bytes(payload),
                content_type,
            )
        except ValueError as err:
            return self.json_message(str(err), status_code=400)

        try:
            await printer.async_print_rasters(
                bitmaps,
                density=options[ATTR_DENSITY],
                feed=options[ATTR_FEED],
            )
        except HomeAssistantError as err:
            return self.json_message(str(err), status_code=502)
        return self.json({"status": "printed"})


async def _async_print_text(hass: HomeAssistant, data: dict[str, Any]) -> None:
    """Print text using the configured entry selected by a service or HTTP call."""
    printers: dict[str, LuckJinglePrinter] = hass.data[DOMAIN]
    entry_id = data.get(ATTR_CONFIG_ENTRY_ID)
    if entry_id is None:
        if len(printers) != 1:
            raise HomeAssistantError(
                "Set config_entry_id when more than one Luck Jingle printer "
                "is configured"
            )
        printer_to_use = next(iter(printers.values()))
    else:
        printer_to_use = printers.get(entry_id)
        if printer_to_use is None:
            raise HomeAssistantError(
                f"No Luck Jingle printer configured with entry ID {entry_id}"
            )

    await printer_to_use.async_print_text(
        data[ATTR_TEXT],
        density=data[ATTR_DENSITY],
        feed=data[ATTR_FEED],
    )


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the integration."""
    hass.http.register_view(NetworkPrintView())
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a configured printer."""
    printers: dict[str, LuckJinglePrinter] = hass.data.setdefault(DOMAIN, {})
    bluetooth_adapter = entry.options.get(
        CONF_BLUETOOTH_ADAPTER,
        entry.data.get(CONF_BLUETOOTH_ADAPTER, BLUETOOTH_ADAPTER_AUTO),
    )
    printer = LuckJinglePrinter(
        hass,
        entry.data[CONF_ADDRESS],
        entry.data[CONF_NAME],
        bluetooth_adapter=(
            None
            if bluetooth_adapter == BLUETOOTH_ADAPTER_AUTO
            else bluetooth_adapter
        ),
        network_print_enabled=entry.options.get(
            CONF_ENABLE_NETWORK_PRINT,
            entry.data.get(CONF_ENABLE_NETWORK_PRINT, False),
        ),
    )
    printers[entry.entry_id] = printer
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    if not hass.services.has_service(DOMAIN, SERVICE_PRINT_TEXT):

        async def async_print_text(call: ServiceCall) -> None:
            """Print text on the selected printer."""
            await _async_print_text(hass, call.data)

        hass.services.async_register(
            DOMAIN,
            SERVICE_PRINT_TEXT,
            async_print_text,
            schema=PRINT_TEXT_SCHEMA,
        )

    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the printer after its relay options change."""
    await hass.config_entries.async_reload(entry.entry_id)


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
