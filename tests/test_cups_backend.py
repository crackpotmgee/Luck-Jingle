"""Tests for the CUPS-to-Home-Assistant text backend."""

from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import os
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

BACKEND_PATH = Path(__file__).parents[1] / "cups" / "backend" / "luckjingle"
BACKEND_LOADER = importlib.machinery.SourceFileLoader(
    "luckjingle_cups_backend", str(BACKEND_PATH)
)
BACKEND_SPEC = importlib.util.spec_from_loader(
    "luckjingle_cups_backend", BACKEND_LOADER
)
assert BACKEND_SPEC is not None
BACKEND = importlib.util.module_from_spec(BACKEND_SPEC)
BACKEND_LOADER.exec_module(BACKEND)


class CUPSBackendTests(unittest.TestCase):
    """Verify CUPS jobs are forwarded as authenticated text pages."""

    def setUp(self) -> None:
        self.requests: list[tuple[str, str, str, bytes]] = []
        requests = self.requests

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                if self.path.startswith("/redirect"):
                    self.send_response(302)
                    self.send_header("Location", "/destination")
                    self.end_headers()
                    return
                body = self.rfile.read(int(self.headers["Content-Length"]))
                requests.append(
                    (
                        self.path,
                        self.headers["Authorization"],
                        self.headers["Content-Type"],
                        body,
                    )
                )
                self.send_response(200)
                self.end_headers()

            def log_message(self, format: str, *args: object) -> None:
                return

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server_thread = threading.Thread(
            target=self.server.serve_forever,
            daemon=True,
        )
        self.server_thread.start()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.config_path = Path(self.temp_dir.name) / "luckjingle.conf"
        self.config_path.write_text(
            "[homeassistant]\n"
            f"url = http://127.0.0.1:{self.server.server_port}\n"
            "token = test%token\n",
            encoding="utf-8",
        )
        self.environment = patch.dict(
            os.environ,
            {
                "DEVICE_URI": "luckjingle://test-entry",
                "LUCKJINGLE_CUPS_CONFIG": str(self.config_path),
            },
        )
        self.environment.start()

    def tearDown(self) -> None:
        self.environment.stop()
        self.server.shutdown()
        self.server.server_close()
        self.server_thread.join()
        self.temp_dir.cleanup()

    def test_forwards_each_page_for_each_copy_with_bearer_auth(self) -> None:
        job_path = Path(self.temp_dir.name) / "job.txt"
        job_path.write_text("first page\fsecond page", encoding="utf-8")

        result = BACKEND.main(
            [
                "luckjingle://test-entry",
                "123",
                "printer-user",
                "test",
                "2",
                "",
                str(job_path),
            ]
        )

        self.assertEqual(result, 0)
        self.assertEqual(len(self.requests), 4)
        self.assertTrue(
            all(
                path == "/api/luck_jingle/print/test-entry"
                and authorization == "Bearer test%token"
                and content_type == "application/json"
                for path, authorization, content_type, _ in self.requests
            )
        )
        self.assertEqual(
            [json.loads(body)["text"] for _, _, _, body in self.requests],
            ["first page", "second page", "first page", "second page"],
        )

    def test_forwards_pdf_bytes_without_modification(self) -> None:
        pdf_data = b"%PDF-1.4\nCUPS PDF test"
        job_path = Path(self.temp_dir.name) / "job.pdf"
        job_path.write_bytes(pdf_data)

        result = BACKEND.main(
            [
                "luckjingle://test-entry",
                "123",
                "printer-user",
                "test",
                "1",
                "",
                str(job_path),
            ]
        )

        self.assertEqual(result, 0)
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(self.requests[0][2], "application/pdf")
        self.assertEqual(self.requests[0][3], pdf_data)

    def test_forwards_image_bytes_without_modification(self) -> None:
        image_data = b"\x89PNG\r\n\x1a\nPNG test"
        job_path = Path(self.temp_dir.name) / "job.png"
        job_path.write_bytes(image_data)

        result = BACKEND.main(
            [
                "luckjingle://test-entry",
                "123",
                "printer-user",
                "test",
                "1",
                "",
                str(job_path),
            ]
        )

        self.assertEqual(result, 0)
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(self.requests[0][2], "image/png")
        self.assertEqual(self.requests[0][3], image_data)

    def test_rejects_non_utf8_jobs(self) -> None:
        job_path = Path(self.temp_dir.name) / "job.bin"
        job_path.write_bytes(b"\xff")

        with patch("sys.stderr"):
            result = BACKEND.main(
                [
                    "luckjingle://test-entry",
                    "123",
                    "printer-user",
                    "test",
                    "1",
                    "",
                    str(job_path),
                ]
            )

        self.assertEqual(result, 1)
        self.assertEqual(self.requests, [])

    def test_does_not_follow_redirects(self) -> None:
        self.config_path.write_text(
            "[homeassistant]\n"
            f"url = http://127.0.0.1:{self.server.server_port}/redirect\n"
            "token = test%token\n",
            encoding="utf-8",
        )
        job_path = Path(self.temp_dir.name) / "job.txt"
        job_path.write_text("test page", encoding="utf-8")

        with patch("sys.stderr"):
            result = BACKEND.main(
                [
                    "luckjingle://test-entry",
                    "123",
                    "printer-user",
                    "test",
                    "1",
                    "",
                    str(job_path),
                ]
            )

        self.assertEqual(result, 1)
        self.assertEqual(self.requests, [])


if __name__ == "__main__":
    unittest.main()
