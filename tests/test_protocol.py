"""Tests for Luck Jingle printer command and raster helpers."""

import unittest
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

INTEGRATION_PATH = Path(__file__).parents[1] / "custom_components" / "luck_jingle"
PROTOCOL_PATH = INTEGRATION_PATH / "protocol.py"
PROTOCOL_SPEC = spec_from_file_location("luck_jingle_protocol", PROTOCOL_PATH)
assert PROTOCOL_SPEC is not None and PROTOCOL_SPEC.loader is not None
PROTOCOL = module_from_spec(PROTOCOL_SPEC)
PROTOCOL_SPEC.loader.exec_module(PROTOCOL)
DISCOVERY_SPEC = spec_from_file_location(
    "luck_jingle_discovery", INTEGRATION_PATH / "discovery.py"
)
assert DISCOVERY_SPEC is not None and DISCOVERY_SPEC.loader is not None
DISCOVERY = module_from_spec(DISCOVERY_SPEC)
DISCOVERY_SPEC.loader.exec_module(DISCOVERY)

ENABLE = PROTOCOL.ENABLE
STOP = PROTOCOL.STOP
WAKE = PROTOCOL.WAKE
density_command = PROTOCOL.density_command
feed_command = PROTOCOL.feed_command
raster_header = PROTOCOL.raster_header
render_text = PROTOCOL.render_text


class ProtocolTests(unittest.TestCase):
    """Verify wire commands and rendered raster dimensions."""

    def test_command_bytes(self) -> None:
        self.assertEqual(WAKE, bytes(12))
        self.assertEqual(ENABLE, bytes.fromhex("10 ff f1 03"))
        self.assertEqual(STOP, bytes.fromhex("10 ff f1 45"))
        self.assertEqual(density_command(2), bytes.fromhex("10 ff 10 00 02"))
        self.assertEqual(feed_command(80), bytes.fromhex("1b 4a 50"))

    def test_raster_header_encodes_width_and_height(self) -> None:
        self.assertEqual(
            raster_header(300),
            bytes.fromhex("1d 76 30 00 30 00 2c 01"),
        )

    def test_text_renders_to_white_padded_rows(self) -> None:
        bitmap = render_text("Test")
        self.assertEqual(len(bitmap) % 48, 0)
        self.assertTrue(any(bitmap))
        self.assertEqual(len(bitmap), 28 * 48)
        self.assertEqual(bitmap[:48], bytes(48))

    def test_text_that_exceeds_raster_limit_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            render_text("\n" * 85)

    def test_invalid_raster_dimensions_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            raster_header(0)
        with self.assertRaises(ValueError):
            feed_command(256)
        with self.assertRaises(ValueError):
            density_command(3)


class DiscoveryTests(unittest.TestCase):
    """Verify model matching for BLE advertisements."""

    def test_match_lpc50_advertisements(self) -> None:
        self.assertTrue(DISCOVERY.matches_model("LPC50_3F3D_BLE", "lpc50"))
        self.assertFalse(DISCOVERY.matches_model("LPC51_3F3D_BLE", "lpc50"))
        self.assertFalse(DISCOVERY.matches_model(None, "lpc50"))

    def test_display_name_drops_ble_suffix(self) -> None:
        self.assertEqual(
            DISCOVERY.printer_display_name("LPC50_3F3D_BLE", "lpc50"),
            "LPC50_3F3D",
        )


if __name__ == "__main__":
    unittest.main()
