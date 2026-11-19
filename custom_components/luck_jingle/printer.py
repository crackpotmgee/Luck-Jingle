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

from .discovery import ble_device_for_source
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
            if self.bluetooth_adapter is None:
                ble_device = bluetooth.async_ble_device_from_address(
                    self.hass, self.address, connectable=True
                )
            else:
                ble_device = ble_device_for_source(
                    bluetooth.async_scanner_devices_by_address(
                        self.hass, self.address, connectable=True
                    ),
                    self.bluetooth_adapter,
                )
            if ble_device is None:
                if self.bluetooth_adapter is not None:
                    raise HomeAssistantError(
                        f"{self.name} is not currently visible through Bluetooth "
                        f"source {self.bluetooth_adapter}"
                    )
                raise HomeAssistantError(
                    f"{self.name} is not currently visible to Home Assistant Bluetooth"
                )

            client = await self._async_connect(ble_device)
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
        """Connect, clearing a stale BlueZ link once if the first attempt fails."""
        try:
            return await establish_connection(
                BleakClient,
                ble_device,
                self.name,
            )
        except BleakError as first_error:
            _LOGGER.warning(
                "Initial BLE connection to %s failed; clearing its BlueZ link "
                "and retrying: %s",
                self.name,
                first_error,
            )
            try:
                await self._async_disconnect_stale_link()
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
                )
            except BleakError as retry_error:
                raise HomeAssistantError(
                    f"Could not connect to {self.name} over Bluetooth LE after "
                    f"clearing a stale connection: {retry_error}"
                ) from retry_error

    async def _async_disconnect_stale_link(self) -> None:
        """Ask BlueZ to disconnect this printer before retrying GATT."""
        try:
            process = await asyncio.create_subprocess_exec(
                "bluetoothctl",
                "disconnect",
                self.address,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
        except OSError as err:
            raise HomeAssistantError(
                f"Could not start bluetoothctl to reset {self.name}: {err}"
            ) from err

        try:
            output, _ = await asyncio.wait_for(process.communicate(), timeout=10)
        except TimeoutError as err:
            try:
                process.kill()
            except ProcessLookupError:
                pass
            await process.communicate()
            raise HomeAssistantError(
                f"Timed out resetting the Bluetooth connection to {self.name}"
            ) from err

        if process.returncode:
            _LOGGER.warning(
                "bluetoothctl could not disconnect stale link to %s (exit %s): %s",
                self.name,
                process.returncode,
                output.decode(errors="replace").strip(),
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
