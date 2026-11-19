"""Tests for persistent BLE connection handling."""

import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

INTEGRATION_PATH = (
    Path(__file__).parents[1] / "custom_components" / "luck_jingle"
)


def _load_printer_module() -> types.ModuleType:
    """Load the printer module with Home Assistant and BLE imports stubbed."""
    package_name = "luck_jingle_connection_test"
    package = types.ModuleType(package_name)
    package.__path__ = [str(INTEGRATION_PATH)]
    sys.modules[package_name] = package

    def module(name: str, **attributes: object) -> types.ModuleType:
        result = types.ModuleType(name)
        for attribute, value in attributes.items():
            setattr(result, attribute, value)
        return result

    class BleakClient:
        pass

    class HomeAssistant:
        pass

    class HomeAssistantError(Exception):
        pass

    bluetooth = module(
        "homeassistant.components.bluetooth",
        async_ble_device_from_address=lambda *args, **kwargs: None,
        async_scanner_devices_by_address=lambda *args, **kwargs: [],
    )
    protocol = module(
        f"{package_name}.protocol",
        DEFAULT_FONT_SIZE=10,
        ENABLE=b"enable",
        RASTER_CHUNK_SIZE=512,
        STOP=b"stop",
        WAKE=b"wake",
        WIDTH_BYTES=48,
        density_command=lambda density: b"density",
        feed_command=lambda feed: b"feed",
        raster_header=lambda rows: b"raster",
        render_text=lambda text, font_size=10: b"",
    )
    homeassistant = module("homeassistant")
    components = module("homeassistant.components", bluetooth=bluetooth)
    core = module("homeassistant.core", HomeAssistant=HomeAssistant)
    exceptions = module(
        "homeassistant.exceptions",
        HomeAssistantError=HomeAssistantError,
    )
    bleak = module("bleak", BleakClient=BleakClient)
    characteristic = module(
        "bleak.backends.characteristic",
        BleakGATTCharacteristic=type("BleakGATTCharacteristic", (), {}),
    )
    device = module("bleak.backends.device", BLEDevice=type("BLEDevice", (), {}))
    bleak_error = module("bleak.exc", BleakError=type("BleakError", (Exception,), {}))
    connector = module(
        "bleak_retry_connector",
        establish_connection=AsyncMock(),
    )
    fake_modules = {
        "homeassistant": homeassistant,
        "homeassistant.components": components,
        "homeassistant.components.bluetooth": bluetooth,
        "homeassistant.core": core,
        "homeassistant.exceptions": exceptions,
        "bleak": bleak,
        "bleak.backends": module("bleak.backends"),
        "bleak.backends.characteristic": characteristic,
        "bleak.backends.device": device,
        "bleak.exc": bleak_error,
        "bleak_retry_connector": connector,
        f"{package_name}.protocol": protocol,
    }

    previous_modules = {
        name: sys.modules.get(name)
        for name in fake_modules
    }
    sys.modules.update(fake_modules)
    try:
        spec = importlib.util.spec_from_file_location(
            f"{package_name}.printer",
            INTEGRATION_PATH / "printer.py",
        )
        assert spec is not None and spec.loader is not None
        printer_module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = printer_module
        spec.loader.exec_module(printer_module)
        return printer_module
    finally:
        for name, previous in previous_modules.items():
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous


PRINTER_MODULE = _load_printer_module()


class FakeClient:
    """Minimal connected BLE client used by the printer tests."""

    def __init__(self) -> None:
        self.is_connected = True
        self.notify_count = 0
        self.disconnect_count = 0

    async def start_notify(self, uuid: str, callback: object) -> None:
        self.notify_count += 1

    async def disconnect(self) -> None:
        self.disconnect_count += 1
        self.is_connected = False


class PrinterConnectionTests(unittest.IsolatedAsyncioTestCase):
    """Verify connection reuse and cleanup behavior."""

    def _create_printer(
        self, keep_connection_alive: bool, clients: list[FakeClient]
    ) -> tuple[object, AsyncMock]:
        printer = PRINTER_MODULE.LuckJinglePrinter(
            None,
            "printer-address",
            "Test printer",
            keep_connection_alive=keep_connection_alive,
        )
        printer._write = AsyncMock()
        printer._wait_for_ack = AsyncMock()

        async def connect() -> FakeClient:
            client = clients.pop(0)
            await client.start_notify(PRINTER_MODULE.ACK_UUID, None)
            return client

        connector = AsyncMock(side_effect=connect)
        printer._async_connect_printer = connector
        return printer, connector

    async def test_enabled_connection_is_reused_and_closed_on_shutdown(self) -> None:
        client = FakeClient()
        printer, connector = self._create_printer(True, [client])

        await printer.async_print_rasters([bytes(48)])
        await printer.async_print_rasters([bytes(48)])

        connector.assert_awaited_once()
        self.assertEqual(client.notify_count, 1)
        self.assertEqual(client.disconnect_count, 0)

        await printer.async_shutdown()
        self.assertEqual(client.disconnect_count, 1)

    async def test_disconnected_idle_client_is_reconnected(self) -> None:
        first_client = FakeClient()
        second_client = FakeClient()
        printer, connector = self._create_printer(True, [first_client, second_client])

        await printer.async_print_rasters([bytes(48)])
        first_client.is_connected = False
        await printer.async_print_rasters([bytes(48)])

        self.assertEqual(connector.await_count, 2)
        self.assertEqual(first_client.disconnect_count, 0)
        await printer.async_shutdown()
        self.assertEqual(second_client.disconnect_count, 1)

    async def test_disabled_connection_is_disconnected_after_each_job(self) -> None:
        clients = [FakeClient(), FakeClient()]
        printer, connector = self._create_printer(False, clients.copy())

        await printer.async_print_rasters([bytes(48)])
        await printer.async_print_rasters([bytes(48)])

        self.assertEqual(connector.await_count, 2)
        self.assertEqual([client.disconnect_count for client in clients], [1, 1])

    async def test_failed_job_disconnects_persistent_client(self) -> None:
        client = FakeClient()
        printer, _ = self._create_printer(True, [client])
        printer._wait_for_ack.side_effect = RuntimeError("printer did not respond")

        with self.assertRaisesRegex(RuntimeError, "did not respond"):
            await printer.async_print_rasters([bytes(48)])

        self.assertIsNone(printer._client)
        self.assertEqual(client.disconnect_count, 1)


if __name__ == "__main__":
    unittest.main()
