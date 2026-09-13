"""Contract tests for the isolated Kokoro HTTP service."""

from __future__ import annotations

import json
import threading
import unittest
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import server


class FakeService:
    def health(self):
        return {
            "status": "ok",
            "service": "python-kokoro",
            "python": "3.12.0",
            "device": "cuda",
        }

    def synthesize(self, text, voice, speed, lang_code):
        self.last_request = (text, voice, speed, lang_code)
        return b"RIFF-test-wave", {
            "X-Audio-Duration": "1.0",
            "X-Render-Seconds": "0.1",
            "X-Real-Time-Factor": "0.1",
        }


class KokoroServerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.service = FakeService()
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.KokoroRequestHandler)
        self.httpd.kokoro_service = self.service
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.httpd.server_port}"

    def tearDown(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=2)

    def test_health_identifies_the_isolated_service(self) -> None:
        with urlopen(f"{self.base}/health") as response:
            body = json.loads(response.read())
        self.assertEqual(response.status, 200)
        self.assertEqual(body["service"], "python-kokoro")
        self.assertEqual(body["device"], "cuda")

    def test_openai_compatible_speech_route_returns_wav(self) -> None:
        payload = json.dumps(
            {
                "model": "kokoro",
                "input": "Hello.",
                "voice": "af_heart",
                "speed": 0.96,
                "response_format": "wav",
                "language": "a",
            }
        ).encode("utf-8")
        request = Request(
            f"{self.base}/v1/audio/speech",
            data=payload,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urlopen(request) as response:
            body = response.read()

        self.assertEqual(response.status, 200)
        self.assertEqual(response.headers.get_content_type(), "audio/wav")
        self.assertEqual(response.headers["X-Real-Time-Factor"], "0.1")
        self.assertEqual(body, b"RIFF-test-wave")
        self.assertEqual(
            self.service.last_request,
            ("Hello.", "af_heart", 0.96, "a"),
        )

    def test_speech_route_rejects_non_wav_format(self) -> None:
        request = Request(
            f"{self.base}/v1/audio/speech",
            data=json.dumps(
                {"input": "Hello.", "voice": "af_heart", "response_format": "mp3"}
            ).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with self.assertRaises(HTTPError) as raised:
            urlopen(request)
        self.assertEqual(raised.exception.code, 400)


if __name__ == "__main__":
    unittest.main()
