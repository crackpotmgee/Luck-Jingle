"""LuckPrinter command and text raster helpers."""

from __future__ import annotations

import textwrap

from PIL import Image, ImageDraw, ImageFont

WIDTH = 384
WIDTH_BYTES = WIDTH // 8
RASTER_CHUNK_SIZE = 128

WAKE = b"\x00" * 12
ENABLE = b"\x10\xff\xf1\x03"
STOP = b"\x10\xff\xf1\x45"
DENSITY_COMMAND = b"\x10\xff\x10\x00"

PADDING = 8
WRAP_COLUMNS = 60
LINE_HEIGHT = 12
MAX_RASTER_ROWS = 1024


def density_command(level: int) -> bytes:
    """Build the print-density command."""
    if level not in (0, 1, 2):
        raise ValueError("Density must be 0, 1, or 2")
    return DENSITY_COMMAND + bytes((level,))


def feed_command(dots: int) -> bytes:
    """Build the paper-feed command."""
    if not 0 <= dots <= 255:
        raise ValueError("Feed must be between 0 and 255 dots")
    return bytes((0x1B, 0x4A, dots))


def raster_header(rows: int) -> bytes:
    """Build a GS v 0 header for a 384-pixel raster."""
    if not 0 < rows <= 0xFFFF:
        raise ValueError("Raster height must be between 1 and 65535 rows")
    return bytes(
        (
            0x1D,
            0x76,
            0x30,
            0,
            WIDTH_BYTES,
            0,
            rows & 0xFF,
            rows >> 8,
        )
    )


def render_text(text: str) -> bytes:
    """Render text to one-bit rows with black pixels encoded as set bits."""
    font = ImageFont.load_default()
    lines: list[str] = []
    for line in text.splitlines() or [""]:
        lines.extend(
            textwrap.wrap(
                line,
                width=WRAP_COLUMNS,
                break_long_words=True,
                break_on_hyphens=True,
            )
            or [""]
        )

    height = PADDING * 2 + len(lines) * LINE_HEIGHT
    if height > MAX_RASTER_ROWS:
        raise ValueError(
            f"Label is too long; the rendered height must not exceed {MAX_RASTER_ROWS} dots"
        )
    image = Image.new("1", (WIDTH, height), 1)
    draw = ImageDraw.Draw(image)
    try:
        for index, line in enumerate(lines):
            draw.text(
                (PADDING, PADDING + index * LINE_HEIGHT),
                line,
                font=font,
                fill=0,
            )
    except UnicodeError as err:
        raise ValueError("The printer's built-in font only supports basic text") from err

    pixels = image.load()
    bitmap = bytearray(height * WIDTH_BYTES)
    for y in range(height):
        row_offset = y * WIDTH_BYTES
        for x in range(WIDTH):
            if pixels[x, y] == 0:
                bitmap[row_offset + x // 8] |= 0x80 >> (x % 8)
    return bytes(bitmap)
