"""Tests for the application launcher."""

from __future__ import annotations

import unittest

import run_app


class ArgumentTest(unittest.TestCase):
    def test_local_folder_path_option_is_not_supported(self) -> None:
        with self.assertRaises(SystemExit):
            run_app.parse_args(["--folder-path", "workspace"])


if __name__ == "__main__":
    unittest.main()
