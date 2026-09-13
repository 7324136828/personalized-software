"""Tests for podcast model lifecycle management."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from backend import podcast_render


class PipelineCleanupTest(unittest.TestCase):
    def test_close_drops_pipeline_and_empties_initialized_cuda_cache(self) -> None:
        cuda = SimpleNamespace(
            is_initialized=MagicMock(return_value=True),
            empty_cache=MagicMock(),
        )
        pipeline = podcast_render.LazyPipeline("a", "cuda")
        pipeline.pipeline = object()
        pipeline.started = True

        with (
            patch.dict(sys.modules, {"torch": SimpleNamespace(cuda=cuda)}),
            patch.object(podcast_render.gc, "collect") as collect,
        ):
            pipeline.close()

        self.assertIsNone(pipeline.pipeline)
        self.assertFalse(pipeline.started)
        collect.assert_called_once_with()
        cuda.is_initialized.assert_called_once_with()
        cuda.empty_cache.assert_called_once_with()

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
