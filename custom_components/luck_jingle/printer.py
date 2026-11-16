"""BLE transport and printing operations for Luck Jingle printers."""

from __future__ import annotations

import asyncio

from bleak import BleakClient
from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak_retry_connector import establish_connection

from homeassistant.components import bluetooth
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

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


class LuckJinglePrinter:
    """Send text print jobs over the printer's BLE GATT connection."""

    def __init__(self, hass: HomeAssistant, address: str, name: str) -> None:
        """Initialize a printer."""
        self.hass = hass
        self.address = address
        self.name = name
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
        rows = len(bitmap) // WIDTH_BYTES
        if not rows or rows > 0xFFFF:
            raise HomeAssistantError("The rendered label has an unsupported height")

        async with self._job_lock:
            ble_device = bluetooth.async_ble_device_from_address(
                self.hass, self.address, connectable=True
            )
            if ble_device is None:
                raise HomeAssistantError(
                    f"{self.name} is not currently visible to Home Assistant Bluetooth"
                )

            client = await establish_connection(
                BleakClient,
                ble_device,
                self.name,
            )
            self._ack_queue = asyncio.Queue()
            try:
                await client.start_notify(ACK_UUID, self._handle_ack)
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
