"""Tests for the local learning-content backend."""

from __future__ import annotations

import io
import json
import tempfile
import threading
import time
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

from backend.server import DEFAULT_OUTPUT_DIR, create_server, parse_args


class ArgumentTest(unittest.TestCase):
    def test_folder_path_uses_its_output_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            args = parse_args(["--folder-path", str(folder)])

        self.assertEqual(args.folder_path, folder.resolve())
        self.assertEqual(args.output_dir, folder.resolve() / "output")

    def test_default_output_directory_is_unchanged(self) -> None:
        self.assertEqual(parse_args([]).output_dir, DEFAULT_OUTPUT_DIR)

    def test_folder_path_and_output_dir_are_mutually_exclusive(self) -> None:
        with self.assertRaises(SystemExit):
            parse_args(["--folder-path", "workspace", "--output-dir", "content"])


class BackendTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.output = root / "output"
        self.responses = root / "responses"
        self.static = root / "dist"
        self.archives = root / "workspace-archives"
        self.flashcard_audio = root / "flashcard-audio"
        (self.output / "qandas").mkdir(parents=True)
        (self.output / 'podcasts').mkdir(parents=True)
        self.static.mkdir()
        (self.static / "index.html").write_text("<h1>app</h1>", encoding="utf-8")
        (self.output / "qandas" / "reflection.json").write_text(
            json.dumps({"title": "Reflection", "description": "Think", "questions": ["Why?"]}),
            encoding="utf-8",
        )
        self.server = create_server(
            "127.0.0.1",
            0,
            self.output,
            self.responses,
            self.static,
            self.archives,
            self.flashcard_audio,
        )
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

    def upload(self, filename: str, body: bytes):
        request = Request(
            self.base + "/api/workspace/upload",
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/zip",
                "X-File-Name": quote(filename),
            },
        )
        with urlopen(request) as response:
            return response.status, json.loads(response.read())

    def test_manifest_reads_output_without_sync(self) -> None:
        status, manifest = self.request("/api/content/manifest")
        self.assertEqual(status, 200)
        self.assertEqual(manifest["kinds"]["qandas"][0]["file"], "reflection.json")

    def test_workspace_collection_can_be_selected_and_switched(self) -> None:
        collection = Path(self.temporary.name) / "selected-collection"
        for name in ("alpha", "beta"):
            qandas = collection / name / "output" / "qandas"
            qandas.mkdir(parents=True)
            (qandas / f"{name}.json").write_text(
                json.dumps(
                    {"title": name.title(), "description": "New", "questions": ["How?"]}
                ),
                encoding="utf-8",
            )

        with patch("backend.server.select_workspace_folder", return_value=collection):
            status, selection = self.request("/api/workspace/select", "POST", {})

        self.assertEqual(status, 200)
        self.assertFalse(selection["cancelled"])
        self.assertEqual(Path(selection["collectionDirectory"]), collection)
        self.assertEqual(selection["activeWorkspace"], "alpha")
        self.assertEqual(
            [workspace["name"] for workspace in selection["workspaces"]],
            ["alpha", "beta"],
        )

        _, manifest = self.request("/api/content/manifest")
        self.assertEqual(
            [entry["file"] for entry in manifest["kinds"]["qandas"]],
            ["alpha.json"],
        )

        status, active = self.request(
            "/api/workspace/activate",
            "POST",
            {"workspaceId": "beta"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(active["activeWorkspace"], "beta")
        self.assertEqual(Path(active["outputDirectory"]), collection / "beta" / "output")

        _, manifest = self.request("/api/content/manifest")
        self.assertEqual(
            [entry["file"] for entry in manifest["kinds"]["qandas"]],
            ["beta.json"],
        )

    def test_single_workspace_selection_remains_supported(self) -> None:
        workspace = Path(self.temporary.name) / "standalone"
        (workspace / "output").mkdir(parents=True)

        with patch("backend.server.select_workspace_folder", return_value=workspace):
            status, selection = self.request("/api/workspace/select", "POST", {})

        self.assertEqual(status, 200)
        self.assertEqual(selection["activeWorkspace"], ".")
        self.assertEqual(len(selection["workspaces"]), 1)
        self.assertEqual(selection["workspaces"][0]["name"], "standalone")
        self.assertEqual(Path(selection["outputDirectory"]), workspace / "output")

    def test_zip_workspace_is_extracted_listed_and_loaded(self) -> None:
        archive_bytes = io.BytesIO()
        with zipfile.ZipFile(archive_bytes, "w", zipfile.ZIP_DEFLATED) as archive:
            for name in ("alpha", "beta"):
                archive.writestr(
                    f"bundle/{name}/output/qandas/{name}.json",
                    json.dumps(
                        {
                            "title": name.title(),
                            "description": "Uploaded",
                            "questions": ["Why?"],
                        }
                    ),
                )

        status, uploaded = self.upload("study-materials.zip", archive_bytes.getvalue())

        self.assertEqual(status, 201)
        self.assertEqual(uploaded["upload"]["name"], "study-materials")
        self.assertEqual(uploaded["upload"]["workspaceCount"], 2)
        self.assertEqual(
            [workspace["name"] for workspace in uploaded["workspaces"]],
            ["alpha", "beta"],
        )

        _, listing = self.request("/api/workspace/uploads")
        self.assertEqual(len(listing["uploads"]), 1)
        self.assertEqual(listing["uploads"][0]["id"], uploaded["upload"]["id"])

        status, loaded = self.request(
            "/api/workspace/load",
            "POST",
            {"uploadId": uploaded["upload"]["id"]},
        )
        self.assertEqual(status, 200)
        self.assertEqual(loaded["activeWorkspace"], "alpha")

    def test_zip_workspace_rejects_path_traversal(self) -> None:
        archive_bytes = io.BytesIO()
        with zipfile.ZipFile(archive_bytes, "w") as archive:
            archive.writestr("../escaped.txt", "unsafe")

        with self.assertRaises(HTTPError) as raised:
            self.upload("unsafe.zip", archive_bytes.getvalue())

        self.assertEqual(raised.exception.code, 400)
        self.assertFalse((self.archives.parent / "escaped.txt").exists())

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

    def test_flashcard_audio_is_generated_cached_and_served(self) -> None:
        cards = [
            {"front": "What is credibility?", "back": "A measure of predictive reliability."},
            {"front": "What is severity?", "back": "Loss size conditional on an event."},
        ]
        wav = b"RIFF-test-wav"

        with patch("backend.server.podcast_render.synthesize_wav", return_value=wav) as synthesize:
            status, generated = self.request(
                "/api/flashcards/audio",
                "POST",
                {"cards": cards},
            )
            self.assertEqual(status, 200)
            self.assertEqual(len(generated["cards"]), 2)
            self.assertEqual(synthesize.call_count, 4)

            self.request("/api/flashcards/audio", "POST", {"cards": cards})
            self.assertEqual(synthesize.call_count, 4)

        with urlopen(self.base + generated["cards"][0]["front"]) as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(response.headers.get_content_type(), "audio/wav")
            self.assertEqual(response.read(), wav)

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

    def test_generate_podcast_starts_background_job(self) -> None:
        from backend import server

        seen: list[list[str]] = []
        finished = threading.Event()

        def fake_render_library(paths, **kwargs):
            seen.append(sorted(Path(p).name for p in paths))
            finished.set()
            return {"generated": ["sample.mp3"], "skipped": [], "failed": []}

        original = server.podcast_render.render_library
        server.podcast_render.render_library = fake_render_library
        server.podcast_job.update(state="idle", startedAt=None, finishedAt=None, result=None)
        try:
            status, body = self.request("/api/generate_podcast", "POST", {})
            self.assertEqual(status, 202)
            self.assertEqual(body["status"], "started")
            self.assertEqual(body["podcasts"], 1)

            self.assertTrue(finished.wait(timeout=5))
            for _ in range(100):
                _, state = self.request("/api/generate_podcast")
                if state["state"] == "done":
                    break
                time.sleep(0.02)
            self.assertEqual(state["state"], "done")
            self.assertEqual(
                state["result"], {"generated": ["sample.mp3"], "skipped": [], "failed": []}
            )
            self.assertEqual(seen, [["sample.json"]])
        finally:
            server.podcast_render.render_library = original
            server.podcast_job.update(state="idle", startedAt=None, finishedAt=None, result=None)

    def test_podcast_log_endpoint_returns_incremental_render_messages(self) -> None:
        from backend import server

        server.PODCAST_LOG_HANDLER.clear()
        server.PODCAST_LOG.info("Rendering test turn %d", 1)

        status, body = self.request("/api/generate_podcast/logs?limit=10")

        self.assertEqual(status, 200)
        self.assertEqual(body["capacity"], server.PODCAST_LOG_CAPACITY)
        self.assertEqual(body["entries"][-1]["level"], "INFO")
        self.assertEqual(body["entries"][-1]["message"], "Rendering test turn 1")
        self.assertIn("timestamp", body["entries"][-1])
        self.assertIn("job", body)

        last_id = body["nextAfter"]
        server.PODCAST_LOG.warning("Second message")
        _, incremental = self.request(
            f"/api/generate_podcast/logs?after={last_id}&limit=10"
        )
        self.assertEqual(
            [entry["message"] for entry in incremental["entries"]],
            ["Second message"],
        )

    def test_podcast_log_endpoint_rejects_invalid_limit(self) -> None:
        with self.assertRaises(HTTPError) as raised:
            self.request("/api/generate_podcast/logs?limit=0")
        self.assertEqual(raised.exception.code, 400)


class NestedLayoutTest(unittest.TestCase):
    """The per-subject layout: new_output/<subject>/<kind>/<file>."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.output = root / "new_output"
        self.responses = root / "responses"
        self.static = root / "dist"
        self.static.mkdir(parents=True)
        (self.static / "index.html").write_text("<h1>app</h1>", encoding="utf-8")

        for subject, stem in (("classical_chinese", "heart_sutra"), ("getting_r", "intro_r")):
            quizzes = self.output / subject / "quizzes"
            quizzes.mkdir(parents=True)
            (quizzes / f"quiz_{stem}.json").write_text(
                json.dumps({"title": f"Quiz {stem}", "questions": []}),
                encoding="utf-8",
            )

        self.server = create_server("127.0.0.1", 0, self.output, self.responses, self.static)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temporary.cleanup()

    def test_manifest_merges_every_subject(self) -> None:
        with urlopen(self.base + "/api/content/manifest") as response:
            manifest = json.loads(response.read())
        quizzes = manifest["kinds"]["quizzes"]
        self.assertEqual(
            {entry["file"] for entry in quizzes},
            {"quiz_heart_sutra.json", "quiz_intro_r.json"},
        )
        self.assertEqual(
            {entry["subject"] for entry in quizzes},
            {"classical_chinese", "getting_r"},
        )

    def test_serves_a_document_from_its_subject_folder(self) -> None:
        with urlopen(self.base + "/api/content/quizzes/quiz_intro_r.json") as response:
            self.assertEqual(response.status, 200)
            body = json.loads(response.read())
        self.assertEqual(body["title"], "Quiz intro_r")


if __name__ == "__main__":
    unittest.main()
