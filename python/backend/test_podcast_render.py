"""Tests for podcast model lifecycle management."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import MagicMock, patch

from backend import podcast_render


class PipelineCleanupTest(unittest.TestCase):
    def test_write_wav_logs_real_time_factor(self) -> None:
        turn = podcast_render.Turn(
            "Introduction", "host", "af_heart", "Hello.", 1.0, 0
        )

        def pipeline(text, *, voice, speed):
            del voice, speed
            yield text, "", [0.0] * 2_400

        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "turn.wav"
            with self.assertLogs("podcast", level="INFO") as captured:
                duration = podcast_render.write_wav([turn], output, pipeline)

        self.assertAlmostEqual(duration, 0.1)
        self.assertTrue(
            any(
                "6 chars -> 0.10s audio" in message and "RTF" in message
                for message in captured.output
            )
        )

    def test_remote_pipeline_posts_openai_compatible_request_and_reads_wav(self) -> None:
        output = io.BytesIO()
        with wave.open(output, "wb") as target:
            target.setnchannels(1)
            target.setsampwidth(2)
            target.setframerate(podcast_render.SAMPLE_RATE)
            target.writeframes(b"\x00\x00" * 2_400)

        response = MagicMock()
        response.__enter__.return_value = response
        response.read.return_value = output.getvalue()
        response.headers = {
            "X-Render-Seconds": "0.25",
            "X-Real-Time-Factor": "0.1",
        }
        with patch.object(
            podcast_render.urllib.request, "urlopen", return_value=response
        ) as urlopen:
            pipeline = podcast_render.RemoteKokoroPipeline("a", "cuda")
            chunks = list(pipeline("Hello.", voice="af_heart", speed=0.96))

        request = urlopen.call_args.args[0]
        payload = json.loads(request.data)
        self.assertEqual(request.full_url, f"{podcast_render.KOKORO_BASE_URL}/audio/speech")
        self.assertEqual(payload["model"], "kokoro")
        self.assertEqual(payload["voice"], "af_heart")
        self.assertEqual(payload["language"], "a")
        self.assertEqual(len(chunks[0][2]), 2_400)

    def test_close_drops_remote_pipeline(self) -> None:
        pipeline = podcast_render.LazyPipeline("a", "cuda")
        pipeline.pipeline = object()
        pipeline.started = True

        pipeline.close()

        self.assertIsNone(pipeline.pipeline)
        self.assertFalse(pipeline.started)

    def test_render_library_closes_pipeline_when_render_is_interrupted(self) -> None:
        pipeline = MagicMock()
        pipeline_type = MagicMock(return_value=pipeline)

        with (
            patch.object(podcast_render, "LazyPipeline", pipeline_type),
            patch.object(podcast_render, "load_episode", side_effect=KeyboardInterrupt),
            self.assertRaises(KeyboardInterrupt),
        ):
            podcast_render.render_library([Path("episode.json")])

        pipeline.close.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
