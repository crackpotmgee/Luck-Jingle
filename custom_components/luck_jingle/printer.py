"""BLE transport and printing operations for Luck Jingle printers."""

from __future__ import annotations

import asyncio
import logging

from bleak import BleakClient
from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak.exc import BleakError
from bleak_retry_connector import establish_connection

from homeassistant.components import bluetooth
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from .discovery import scanner_devices_in_connection_order
from .protocol import (
    ENABLE,
    RASTER_CHUNK_SIZE,
    STOP,
    WAKE,
    WIDTH_BYTES,
    density_command,
    feed_command,
    raster_header,
    render_text,
)

WRITE_UUID = "0000ff02-0000-1000-8000-00805f9b34fb"
ACK_UUID = "0000ff01-0000-1000-8000-00805f9b34fb"

ACK_TIMEOUT = 10
RASTER_ACK_TIMEOUT = 60
BLE_CONNECT_TIMEOUT = 15
DBUS_COMMAND_TIMEOUT = 5
WRITE_DELAY = 0.035
_LOGGER = logging.getLogger(__name__)


class LuckJinglePrinter:
    """Send text print jobs over the printer's BLE GATT connection."""

    def __init__(
        self,
        hass: HomeAssistant,
        address: str,
        name: str,
        *,
        bluetooth_adapter: str | None = None,
        network_print_enabled: bool = False,
    ) -> None:
        """Initialize a printer."""
        self.hass = hass
        self.address = address
        self.name = name
        self.bluetooth_adapter = bluetooth_adapter
        self.network_print_enabled = network_print_enabled
        self._job_lock = asyncio.Lock()
        self._ack_queue: asyncio.Queue[bytes] = asyncio.Queue()

    async def async_print_text(
        self, text: str, *, density: int = 1, feed: int = 80
    ) -> None:
        """Render and print a text label."""
        try:
            bitmap = render_text(text)
        except ValueError as err:
            raise HomeAssistantError(str(err)) from err
        await self.async_print_rasters([bitmap], density=density, feed=feed)

    async def async_print_rasters(
        self, bitmaps: list[bytes], *, density: int = 1, feed: int = 80
    ) -> None:
        """Send one or more already-rendered pages to the printer."""
        if not bitmaps:
            raise HomeAssistantError("The print job contains no raster pages")
        for bitmap in bitmaps:
            rows = len(bitmap) // WIDTH_BYTES
            if len(bitmap) % WIDTH_BYTES or not rows or rows > 0xFFFF:
                raise HomeAssistantError("The rendered label has an unsupported height")

        async with self._job_lock:
            scanner_devices = list(
                bluetooth.async_scanner_devices_by_address(
                    self.hass,
                    self.address,
                    connectable=True,
                )
            )
            ordered_devices = scanner_devices_in_connection_order(
                scanner_devices,
                self.bluetooth_adapter,
            )
            connection_candidates: list[tuple[str, BLEDevice]] = []
            seen_paths: set[str] = set()
            seen_devices: set[int] = set()

            def add_candidate(source: str, device: BLEDevice) -> None:
                path = _bluez_device_path(device)
                if path is not None:
                    if path in seen_paths:
                        return
                    seen_paths.add(path)
                else:
                    device_id = id(device)
                    if device_id in seen_devices:
                        return
                    seen_devices.add(device_id)
                connection_candidates.append((source, device))

            if self.bluetooth_adapter is None:
                preferred_device = bluetooth.async_ble_device_from_address(
                    self.hass, self.address, connectable=True
                )
                if preferred_device is not None:
                    preferred_path = _bluez_device_path(preferred_device)
                    preferred_source = next(
                        (
                            device.scanner.source
                            for device in scanner_devices
                            if (
                                preferred_path is not None
                                and _bluez_device_path(device.ble_device)
                                == preferred_path
                            )
                            or device.ble_device is preferred_device
                        ),
                        "automatic",
                    )
                    add_candidate(preferred_source, preferred_device)

            for scanner_device in ordered_devices:
                add_candidate(
                    scanner_device.scanner.source,
                    scanner_device.ble_device,
                )

            if not connection_candidates:
                if self.bluetooth_adapter is not None:
                    raise HomeAssistantError(
                        f"{self.name} is not currently visible through Bluetooth "
                        f"source {self.bluetooth_adapter}"
                    )
                raise HomeAssistantError(
                    f"{self.name} is not currently visible to Home Assistant Bluetooth"
                )

            client = None
            connection_errors: list[str] = []
            for index, (source, ble_device) in enumerate(connection_candidates):
                try:
                    client = await self._async_connect(ble_device)
                    if index:
                        _LOGGER.warning(
                            "Connected to %s through Bluetooth source %s after "
                            "the preferred source failed",
                            self.name,
                            source,
                        )
                    break
                except HomeAssistantError as err:
                    connection_errors.append(f"{source}: {err}")
                    if index + 1 < len(connection_candidates):
                        _LOGGER.warning(
                            "Could not connect to %s through Bluetooth source %s; "
                            "trying another visible source: %s",
                            self.name,
                            source,
                            err,
                        )
            if client is None:
                raise HomeAssistantError(
                    f"Could not connect to {self.name} over Bluetooth LE using "
                    f"any visible source: {'; '.join(connection_errors)}"
                )

            self._ack_queue = asyncio.Queue()
            try:
                await client.start_notify(ACK_UUID, self._handle_ack)
                for bitmap in bitmaps:
                    rows = len(bitmap) // WIDTH_BYTES
                    self._ack_queue = asyncio.Queue()
                    await self._write(client, WAKE)
                    await self._write(client, ENABLE)
                    await self._write(client, density_command(density))
                    await self._wait_for_ack(ACK_TIMEOUT)

                    await self._write(
                        client,
                        raster_header(rows) + bitmap,
                        chunk_size=RASTER_CHUNK_SIZE,
                    )
                    await self._wait_for_ack(RASTER_ACK_TIMEOUT)
                    await self._write(client, feed_command(feed))
                    await self._write(client, STOP)
            finally:
                await client.disconnect()

    async def _async_connect(self, ble_device: BLEDevice) -> BleakClient:
        """Prefer LE and retry once after disconnecting a stale BlueZ link."""
        await self._async_set_le_bearer(ble_device)
        try:
            return await establish_connection(
                BleakClient,
                ble_device,
                self.name,
                max_attempts=1,
                timeout=BLE_CONNECT_TIMEOUT,
            )
        except BleakError as first_error:
            _LOGGER.warning(
                "Initial BLE connection to %s failed; clearing its BlueZ link "
                "and retrying: %s",
                self.name,
                first_error,
            )
            try:
                await self._async_disconnect_stale_link(ble_device)
            except HomeAssistantError as err:
                raise HomeAssistantError(
                    f"Could not connect to {self.name} over Bluetooth LE: "
                    f"{first_error}. Clearing the stale connection also failed: {err}"
                ) from err

            try:
                return await establish_connection(
                    BleakClient,
                    ble_device,
                    self.name,
                    max_attempts=1,
                    timeout=BLE_CONNECT_TIMEOUT,
                )
            except BleakError as retry_error:
                raise HomeAssistantError(
                    f"Could not connect to {self.name} over Bluetooth LE after "
                    f"clearing a stale connection: {retry_error}"
                ) from retry_error

    async def _async_set_le_bearer(self, ble_device: BLEDevice) -> None:
        """Tell BlueZ to use LE for this dual-mode printer."""
        path = _bluez_device_path(ble_device)
        properties = ble_device.details.get("props")
        if (
            path is None
            or not isinstance(properties, dict)
            or "PreferredBearer" not in properties
            or properties["PreferredBearer"] == "le"
        ):
            return

        await self._async_bluez_device_command(
            path,
            "org.freedesktop.DBus.Properties.Set",
            "string:org.bluez.Device1",
            "string:PreferredBearer",
            "variant:string:le",
        )

    async def _async_disconnect_stale_link(self, ble_device: BLEDevice) -> None:
        """Ask BlueZ to disconnect this adapter's printer link before retrying."""
        path = _bluez_device_path(ble_device)
        if path is None:
            return

        try:
            await self._async_bluez_device_command(
                path,
                "org.bluez.Device1.Disconnect",
            )
        except HomeAssistantError as err:
            if "org.bluez.Error.NotConnected" not in str(err):
                raise

    async def _async_bluez_device_command(
        self, path: str, member: str, *arguments: str
    ) -> None:
        """Run one BlueZ D-Bus operation for the selected adapter device."""
        try:
            process = await asyncio.create_subprocess_exec(
                "dbus-send",
                "--system",
                "--print-reply",
                "--dest=org.bluez",
                path,
                member,
                *arguments,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
        except OSError as err:
            raise HomeAssistantError(
                f"Could not run a BlueZ command for {self.name}: {err}"
            ) from err

        try:
            output, _ = await asyncio.wait_for(
                process.communicate(),
                timeout=DBUS_COMMAND_TIMEOUT,
            )
        except TimeoutError as err:
            try:
                process.kill()
            except ProcessLookupError:
                pass
            await process.communicate()
            raise HomeAssistantError(
                f"Timed out running a BlueZ command for {self.name}"
            ) from err

        if process.returncode:
            raise HomeAssistantError(
                f"BlueZ could not run a command for {self.name}: "
                f"{output.decode(errors='replace').strip()}"
            )

    async def _write(
        self,
        client: BleakClient,
        payload: bytes,
        *,
        chunk_size: int | None = None,
    ) -> None:
        """Write a command or chunked raster to the printer."""
        size = chunk_size or len(payload)
        for offset in range(0, len(payload), size):
            await client.write_gatt_char(
                WRITE_UUID,
                payload[offset : offset + size],
                response=True,
            )
            await asyncio.sleep(WRITE_DELAY)

    async def _wait_for_ack(self, timeout: int) -> None:
        """Wait for the printer's OK response."""
        received = bytearray()
        try:
            while b"OK" not in received:
                received.extend(await asyncio.wait_for(self._ack_queue.get(), timeout))
        except TimeoutError as err:
            raise HomeAssistantError(
                f"{self.name} did not acknowledge the print command"
            ) from err

    def _handle_ack(
        self, characteristic: BleakGATTCharacteristic, data: bytearray
    ) -> None:
        """Queue bytes received on the printer's acknowledgement characteristic."""
        self._ack_queue.put_nowait(bytes(data))


def _bluez_device_path(ble_device: BLEDevice) -> str | None:
    """Return a local BlueZ device path, if this device uses BlueZ."""
    path = ble_device.details.get("path")
    if isinstance(path, str) and path.startswith("/org/bluez/hci"):
        return path
    return None
