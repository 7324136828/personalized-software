"""Compatibility entry point for the canonical Kokoro podcast renderer.

Run ``python python/podcasts.py --help``. The implementation remains in
``python/podcast.py`` so existing imports and commands continue to work.
"""

from podcast import main


if __name__ == "__main__":
    raise SystemExit(main())
