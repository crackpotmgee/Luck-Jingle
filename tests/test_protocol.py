"""Tests for Luck Jingle printer command and raster helpers."""

import unittest
from importlib.util import module_from_spec, spec_from_file_location
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

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
DEFAULT_FONT_SIZE = PROTOCOL.DEFAULT_FONT_SIZE
MAX_FONT_SIZE = PROTOCOL.MAX_FONT_SIZE
MIN_FONT_SIZE = PROTOCOL.MIN_FONT_SIZE
MAX_DOCUMENT_BYTES = PROTOCOL.MAX_DOCUMENT_BYTES
STOP = PROTOCOL.STOP
WAKE = PROTOCOL.WAKE
density_command = PROTOCOL.density_command
feed_command = PROTOCOL.feed_command
raster_header = PROTOCOL.raster_header
render_document = PROTOCOL.render_document
render_image = PROTOCOL.render_image
render_text = PROTOCOL.render_text


def _pdf_with_pages(page_count: int) -> bytes:
    """Build a minimal PDF fixture without external tooling."""
    page_references = " ".join(
        f"{3 + page_index * 2} 0 R" for page_index in range(page_count)
    )
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        (
            f"<< /Type /Pages /Kids [{page_references}] /Count {page_count} >>"
        ).encode(),
    ]
    for page_index in range(page_count):
        page_object = 3 + page_index * 2
        content_object = page_object + 1
        objects.extend(
            [
                (
                    f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 72 72] "
                    f"/Resources << >> /Contents {content_object} 0 R >>"
                ).encode(),
                b"<< /Length 0 >>\nstream\n\nendstream",
            ]
        )
    document = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, body in enumerate(objects, 1):
        offsets.append(len(document))
        document.extend(f"{index} 0 obj\n".encode() + body + b"\nendobj\n")
    xref_offset = len(document)
    document.extend(f"xref\n0 {len(offsets)}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        document.extend(f"{offset:010} 00000 n \n".encode())
    document.extend(
        f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n".encode()
    )
    return bytes(document)


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

    def test_increased_font_size_scales_text_and_wraps_long_words(self) -> None:
        normal = render_text("Test")
        larger = render_text("Test", font_size=20)
        wrapped = render_text("W" * 60, font_size=MAX_FONT_SIZE)

        self.assertGreater(len(larger), len(normal))
        self.assertGreater(len(wrapped), len(render_text("W", font_size=MAX_FONT_SIZE)))

    def test_actual_and_escaped_newlines_render_as_separate_lines(self) -> None:
        single_line = render_text("First", font_size=20)
        actual_newlines = render_text("First\r\nSecond", font_size=20)
        escaped_newlines = render_text(r"First\nSecond", font_size=20)

        self.assertGreater(len(actual_newlines), len(single_line))
        self.assertEqual(escaped_newlines, actual_newlines)

    def test_font_size_is_bounded(self) -> None:
        with self.assertRaises(ValueError):
            render_text("Test", font_size=MIN_FONT_SIZE - 1)
        with self.assertRaises(ValueError):
            render_text("Test", font_size=MAX_FONT_SIZE + 1)

    def test_text_that_exceeds_raster_limit_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            render_text("\n" * 85)

    def test_image_is_resized_to_printer_width(self) -> None:
        image = Image.new("RGB", (2, 1), "black")
        image_data = BytesIO()
        image.save(image_data, format="PNG")

        bitmaps = render_image(image_data.getvalue())

        self.assertEqual(len(bitmaps), 1)
        self.assertEqual(len(bitmaps[0]), 192 * 48)
        self.assertTrue(any(bitmaps[0]))

    def test_transparent_image_background_prints_white(self) -> None:
        image = Image.new("RGBA", (1, 1), (0, 0, 0, 0))
        image_data = BytesIO()
        image.save(image_data, format="PNG")

        self.assertFalse(any(render_image(image_data.getvalue())[0]))

    def test_pdf_pages_render_to_separate_printer_width_bitmaps(self) -> None:
        bitmaps = render_document(_pdf_with_pages(2), "application/pdf")

        self.assertEqual(len(bitmaps), 2)
        self.assertTrue(all(len(bitmap) == 384 * 48 for bitmap in bitmaps))

    def test_invalid_pdf_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            render_document(b"not a PDF", "application/pdf")

    def test_oversized_document_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            render_document(
                b"x" * (MAX_DOCUMENT_BYTES + 1),
                "application/octet-stream",
            )

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

    def test_adapter_options_include_names_and_sources(self) -> None:
        devices = [
            SimpleNamespace(
                scanner=SimpleNamespace(
                    source="88:A2:9E:34:50:9B",
                    name="Home Assistant",
                    adapter="hci1",
                )
            ),
            SimpleNamespace(
                scanner=SimpleNamespace(
                    source="8A:88:4B:E3:47:E4",
                    name="Home Assistant #1",
                    adapter="hci0",
                )
            ),
        ]

        self.assertEqual(
            DISCOVERY.adapter_options(devices),
            [
                (
                    "88:A2:9E:34:50:9B",
                    "Home Assistant (hci1) - 88:A2:9E:34:50:9B",
                ),
                (
                    "8A:88:4B:E3:47:E4",
                    "Home Assistant #1 (hci0) - 8A:88:4B:E3:47:E4",
                ),
            ],
        )

    def test_selects_ble_device_for_requested_source(self) -> None:
        hci0_device = object()
        hci1_device = object()
        devices = [
            SimpleNamespace(
                scanner=SimpleNamespace(source="hci0"),
                ble_device=hci0_device,
            ),
            SimpleNamespace(
                scanner=SimpleNamespace(source="hci1"),
                ble_device=hci1_device,
            ),
        ]

        self.assertIs(
            DISCOVERY.ble_device_for_source(devices, "hci1"), hci1_device
        )
        self.assertIsNone(DISCOVERY.ble_device_for_source(devices, "hci2"))

    def test_orders_selected_source_first_and_keeps_fallbacks(self) -> None:
        hci0_device = SimpleNamespace(
            scanner=SimpleNamespace(source="hci0"),
        )
        hci1_device = SimpleNamespace(
            scanner=SimpleNamespace(source="hci1"),
        )
        devices = [hci0_device, hci1_device]

        self.assertEqual(
            DISCOVERY.scanner_devices_in_connection_order(devices, "hci1"),
            [hci1_device, hci0_device],
        )
        self.assertEqual(
            DISCOVERY.scanner_devices_in_connection_order(devices, None),
            devices,
        )
        self.assertEqual(
            DISCOVERY.scanner_devices_in_connection_order(devices, "missing"),
            devices,
        )


if __name__ == "__main__":
    unittest.main()
