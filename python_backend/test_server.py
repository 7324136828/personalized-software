"""Tests for the local learning-content backend."""

from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from python_backend.server import create_server


class BackendTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.output = root / "output"
        self.responses = root / "responses"
        self.static = root / "dist"
        (self.output / "qandas").mkdir(parents=True)
        (self.output / 'podcasts').mkdir(parents=True)
        self.static.mkdir()
        (self.static / "index.html").write_text("<h1>app</h1>", encoding="utf-8")
        (self.output / "qandas" / "reflection.json").write_text(
            json.dumps({"title": "Reflection", "description": "Think", "questions": ["Why?"]}),
            encoding="utf-8",
        )
        self.server = create_server("127.0.0.1", 0, self.output, self.responses, self.static)
        (self.output / 'podcasts' / 'sample.json').write_text(
            json.dumps(
                {
                    'episode_title': 'Sample Episode',
                    'podcast_show': 'Test Show',
                    'cast': [{'speaker_id': 'host', 'voice_file': 'af_heart'}],
                    'script': [
                        {
                            'segment_name': 'Intro',
                            'scenes': [{'speaker_id': 'host', 'dialogue': 'Hello.'}],
                        }
                    ],
                }
            ),
            encoding='utf-8',
        )
        (self.output / 'podcasts' / 'sample.mp3').write_bytes(b'ID3-test-audio')
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temporary.cleanup()

    def request(self, path: str, method: str = "GET", payload: object | None = None):
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = Request(
            self.base + path,
            data=data,
            method=method,
            headers={"Content-Type": "application/json"},
        )
        with urlopen(request) as response:
            return response.status, json.loads(response.read())

    def test_manifest_reads_output_without_sync(self) -> None:
        status, manifest = self.request("/api/content/manifest")
        self.assertEqual(status, 200)
        self.assertEqual(manifest["kinds"]["qandas"][0]["file"], "reflection.json")

    def test_podcast_manifest_and_audio_download(self) -> None:
        status, manifest = self.request('/api/content/manifest')
        self.assertEqual(status, 200)
        podcast = manifest['kinds']['podcasts'][0]
        self.assertEqual(podcast['title'], 'Sample Episode')
        self.assertEqual(podcast['sidecars'], ['sample.mp3'])

        with urlopen(self.base + '/api/content/podcasts/sample.mp3') as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(response.headers.get_content_type(), 'audio/mpeg')
            self.assertEqual(response.read(), b'ID3-test-audio')

    def test_qanda_session_round_trip(self) -> None:
        status, session = self.request(
            "/api/qa/sessions",
            "POST",
            {
                "qaFile": "reflection.json",
                "title": "Reflection",
                "questions": [{"id": "one", "question": "Why?"}],
            },
        )
        self.assertEqual(status, 201)

        status, updated = self.request(
            f"/api/qa/sessions/{session['id']}",
            "PUT",
            {"answers": ["Because."], "currentQuestion": 0, "completed": True},
        )
        self.assertEqual(status, 200)
        self.assertEqual(updated["status"], "completed")
        self.assertEqual(updated["responses"][0]["answer"], "Because.")

        status, restored = self.request(f"/api/qa/sessions/{session['id']}")
        self.assertEqual(status, 200)
        self.assertEqual(restored, updated)

    def test_content_path_traversal_is_rejected(self) -> None:
        with self.assertRaises(HTTPError) as raised:
            self.request("/api/content/qandas/../../outside.json")
        self.assertIn(raised.exception.code, {400, 404})


if __name__ == "__main__":
    unittest.main()
