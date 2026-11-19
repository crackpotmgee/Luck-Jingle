"""LuckPrinter command and text raster helpers."""

from __future__ import annotations

import textwrap
from io import BytesIO

import pypdfium2 as pdfium
from PIL import Image, ImageDraw, ImageFont, ImageOps
from PIL.Image import DecompressionBombError

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
MAX_DOCUMENT_PAGES = 20
MAX_DOCUMENT_BYTES = 8 * 1024 * 1024
MAX_IMAGE_PIXELS = 12_000_000
IMAGE_FORMATS = {"BMP", "GIF", "JPEG", "PNG", "TIFF", "WEBP"}


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

    return _encode_bitmap(image)


def render_image(data: bytes) -> list[bytes]:
    """Render supported raster image frames to printer-width bitmaps."""
    try:
        with Image.open(BytesIO(data)) as image:
            image_format = image.format
            frame_count = getattr(image, "n_frames", 1)
            if image_format not in IMAGE_FORMATS:
                raise ValueError(f"Unsupported image format: {image_format}")
            if frame_count > MAX_DOCUMENT_PAGES:
                raise ValueError(
                    f"Images may contain at most {MAX_DOCUMENT_PAGES} frames"
                )

            bitmaps = []
            for frame_index in range(frame_count):
                image.seek(frame_index)
                if image.width * image.height > MAX_IMAGE_PIXELS:
                    raise ValueError(
                        f"Image frames must not exceed {MAX_IMAGE_PIXELS} pixels"
                    )
                frame = image.copy()
                try:
                    bitmaps.append(_render_pil_image(frame))
                finally:
                    frame.close()
            return bitmaps
    except (EOFError, OSError, DecompressionBombError) as err:
        raise ValueError("The uploaded image is invalid or unsupported") from err


def render_pdf(data: bytes) -> list[bytes]:
    """Render each PDF page to a printer-width bitmap."""
    if not data.startswith(b"%PDF-"):
        raise ValueError("The uploaded document is not a PDF")

    try:
        document = pdfium.PdfDocument(data)
    except (pdfium.PdfiumError, ValueError) as err:
        raise ValueError("The uploaded PDF could not be opened") from err

    try:
        page_count = len(document)
        if page_count == 0:
            raise ValueError("The PDF contains no pages")
        if page_count > MAX_DOCUMENT_PAGES:
            raise ValueError(
                f"PDFs may contain at most {MAX_DOCUMENT_PAGES} pages"
            )

        bitmaps = []
        for page_index in range(page_count):
            page = document[page_index]
            try:
                page_width, page_height = page.get_size()
                if page_width <= 0 or page_height <= 0:
                    raise ValueError("The PDF contains a page with invalid dimensions")
                scale = min(
                    WIDTH / page_width,
                    MAX_RASTER_ROWS / page_height,
                )
                rendered_page = page.render(scale=scale)
                try:
                    bitmaps.append(_render_pil_image(rendered_page.to_pil()))
                finally:
                    rendered_page.close()
            finally:
                page.close()
        return bitmaps
    except (pdfium.PdfiumError, OSError, ValueError) as err:
        raise ValueError(f"The PDF could not be rendered: {err}") from err
    finally:
        document.close()


def render_document(data: bytes, content_type: str) -> list[bytes]:
    """Render a PDF or supported image document to printer-width bitmaps."""
    if len(data) > MAX_DOCUMENT_BYTES:
        raise ValueError(f"Documents must be at most {MAX_DOCUMENT_BYTES} bytes")
    media_type = content_type.split(";", maxsplit=1)[0].strip().lower()
    if media_type == "application/pdf" or data.startswith(b"%PDF-"):
        return render_pdf(data)
    if media_type == "application/octet-stream" or media_type.startswith("image/"):
        return render_image(data)
    raise ValueError("Only PDF and raster image documents are supported")


def _render_pil_image(image: Image.Image) -> bytes:
    """Fit a PIL image to the print area and convert it to a one-bit raster."""
    image = ImageOps.exif_transpose(image)
    width, height = image.size
    if width <= 0 or height <= 0:
        raise ValueError("Images must have non-zero dimensions")

    scale = min(WIDTH / width, MAX_RASTER_ROWS / height)
    output_size = (max(1, round(width * scale)), max(1, round(height * scale)))
    resized = image.convert("RGBA").resize(output_size, Image.Resampling.LANCZOS)
    background = Image.new("RGBA", (WIDTH, output_size[1]), (255, 255, 255, 255))
    background.alpha_composite(resized, ((WIDTH - output_size[0]) // 2, 0))
    monochrome = background.convert("L").point(
        lambda value: 0 if value < 160 else 255
    ).convert("1")
    return _encode_bitmap(monochrome)


def _encode_bitmap(image: Image.Image) -> bytes:
    """Pack a 384-pixel, one-bit image with black pixels encoded as set bits."""
    if image.width != WIDTH or image.mode != "1":
        raise ValueError("Raster images must be monochrome and 384 pixels wide")
    if not 0 < image.height <= MAX_RASTER_ROWS:
        raise ValueError(
            f"Raster height must be between 1 and {MAX_RASTER_ROWS} rows"
        )

    pixels = image.load()
    bitmap = bytearray(image.height * WIDTH_BYTES)
    for y in range(image.height):
        row_offset = y * WIDTH_BYTES
        for x in range(WIDTH):
            if pixels[x, y] == 0:
                bitmap[row_offset + x // 8] |= 0x80 >> (x % 8)
    return bytes(bitmap)
