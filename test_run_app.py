"""Tests for the application launcher."""

from __future__ import annotations

import unittest
from pathlib import Path

import run_app


class WorkspacePathTest(unittest.TestCase):
    def test_supplied_workspace_is_resolved(self) -> None:
        workspace = Path("supplied-workspace")
        selected = run_app.resolve_workspace_path(workspace)

        self.assertEqual(selected, workspace.resolve())

    def test_missing_workspace_remains_unset_for_website_selection(self) -> None:
        selected = run_app.resolve_workspace_path(None)

        self.assertIsNone(selected)


if __name__ == "__main__":
    unittest.main()
