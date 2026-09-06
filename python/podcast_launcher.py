"""Desktop viewer for podcast JSON and matching MP3/WAV sidecars.

    python python/podcast_launcher.py
    python python/podcast_launcher.py --podcast-dir output/podcasts
"""

from __future__ import annotations

import argparse
import shutil
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import List, Optional, Sequence

from launcher_common import Chunk, LibraryApp, RichText, read_json, require


@dataclass
class CastMember:
    speaker_id: str
    host_id: str
    name: str
    voice_file: str
    style: str


@dataclass
class Scene:
    speaker_id: str
    dialogue: str
    directions: str = ""


@dataclass
class Segment:
    name: str
    scenes: List[Scene]


@dataclass
class PodcastEpisode:
    title: str
    show: str
    cast: List[CastMember]
    segments: List[Segment]
    path: Path
    audio_path: Optional[Path]

    @classmethod
    def load(cls, path: Path) -> "PodcastEpisode":
        data = read_json(path)
        where = path.name
        cast: List[CastMember] = []
        speaker_ids: set[str] = set()
        for index, raw in enumerate(require(data, "cast", list, where)):
            location = f"{where} cast member {index + 1}"
            if not isinstance(raw, dict):
                raise ValueError(f"{location}: must be an object")
            speaker_id = require(raw, "speaker_id", str, location)
            if not speaker_id or speaker_id in speaker_ids:
                raise ValueError(f"{location}: speaker_id must be unique and nonempty")
            speaker_ids.add(speaker_id)
            cast.append(
                CastMember(
                    speaker_id=speaker_id,
                    host_id=str(raw.get("host_id", "")),
                    name=str(raw.get("name", speaker_id)),
                    voice_file=require(raw, "voice_file", str, location),
                    style=str(raw.get("style", "")),
                )
            )
        if not cast:
            raise ValueError(f"{where}: cast must not be empty")

        segments: List[Segment] = []
        spoken = 0
        for index, raw in enumerate(require(data, "script", list, where)):
            location = f"{where} segment {index + 1}"
            if not isinstance(raw, dict):
                raise ValueError(f"{location}: must be an object")
            scenes: List[Scene] = []
            for scene_index, item in enumerate(require(raw, "scenes", list, location)):
                scene_location = f"{location} scene {scene_index + 1}"
                if not isinstance(item, dict):
                    raise ValueError(f"{scene_location}: must be an object")
                speaker_id = require(item, "speaker_id", str, scene_location)
                if speaker_id not in speaker_ids:
                    raise ValueError(f"{scene_location}: unknown speaker {speaker_id!r}")
                dialogue = str(item.get("dialogue", ""))
                spoken += bool(dialogue.strip())
                scenes.append(Scene(speaker_id, dialogue, str(item.get("directions", ""))))
            segments.append(Segment(require(raw, "segment_name", str, location), scenes))
        if not segments or not spoken:
            raise ValueError(f"{where}: script must contain spoken dialogue")

        audio = next(
            (candidate for suffix in (".mp3", ".wav") if (candidate := path.with_suffix(suffix)).is_file()),
            None,
        )
        return cls(
            title=require(data, "episode_title", str, where),
            show=str(data.get("podcast_show", "")),
            cast=cast,
            segments=segments,
            path=path,
            audio_path=audio,
        )

    def turn_count(self) -> int:
        return sum(bool(scene.dialogue.strip()) for segment in self.segments for scene in segment.scenes)


class PodcastApp(LibraryApp):
    window_title = "Podcast Library"
    window_size = "1180x780"

    def load_one(self, path: Path) -> PodcastEpisode:
        return PodcastEpisode.load(path)

    def title_of(self, doc: PodcastEpisode) -> str:
        return doc.title

    def describe(self, doc: PodcastEpisode) -> Sequence[Chunk]:
        return [
            (doc.title + "\n\n", "h2"),
            (f"Show: {doc.show or 'n/a'}\n", "dim"),
            (f"Cast: {', '.join(member.name for member in doc.cast)}\n", "dim"),
            (f"Segments: {len(doc.segments)}\n", "dim"),
            (f"Spoken turns: {doc.turn_count()}\n", "dim"),
            (f"Audio: {doc.audio_path.name if doc.audio_path else 'not generated'}\n", "dim"),
            (f"Script: {doc.path.name}\n", "dim"),
        ]

    def build_toolbar(self, toolbar: ttk.Frame) -> None:
        self.play_button = ttk.Button(toolbar, text="Play audio", command=self._play)
        self.play_button.grid(row=0, column=2)
        self.save_audio_button = ttk.Button(toolbar, text="Save audio as...", command=self._save_audio)
        self.save_audio_button.grid(row=0, column=3, padx=(8, 0))
        ttk.Button(toolbar, text="Save script as...", command=self._save_script).grid(
            row=0, column=4, padx=(8, 0)
        )

    def build_content(self, parent: ttk.Frame) -> None:
        frame = ttk.Frame(parent)
        frame.grid(row=0, column=0, sticky="nsew")
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        self.body = RichText(frame, padx=18, pady=14)
        self.body.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(frame, orient="vertical", command=self.body.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.body.configure(yscrollcommand=scroll.set)

    def show(self, doc: PodcastEpisode) -> None:
        names = {member.speaker_id: member.name for member in doc.cast}
        chunks: List[Chunk] = [(doc.title + "\n", "h1"), (doc.show + "\n", "dim")]
        for segment in doc.segments:
            chunks.append((segment.name + "\n", "h2"))
            for scene in segment.scenes:
                if not scene.dialogue.strip():
                    continue
                chunks.extend(
                    [
                        (names.get(scene.speaker_id, scene.speaker_id) + "\n", "h3"),
                        (scene.dialogue + "\n", "body"),
                    ]
                )
        self.body.set_chunks(chunks)
        state = "normal" if doc.audio_path else "disabled"
        self.play_button.configure(state=state)
        self.save_audio_button.configure(state=state)
        self.set_status(
            f"{len(doc.segments)} segments · {doc.turn_count()} spoken turns · "
            f"{'audio ready' if doc.audio_path else 'script only'}"
        )
        self.set_hint("Play opens the system audio player · Save As creates a local copy")

    def _play(self) -> None:
        doc = self.selected()
        if doc and doc.audio_path:
            webbrowser.open(doc.audio_path.resolve().as_uri())

    def _save(self, source: Path, label: str) -> None:
        destination = filedialog.asksaveasfilename(
            parent=self,
            title=f"Save {label}",
            initialfile=source.name,
            defaultextension=source.suffix,
        )
        if destination:
            shutil.copy2(source, destination)
            messagebox.showinfo("Saved", f"Saved to {destination}", parent=self)

    def _save_audio(self) -> None:
        doc = self.selected()
        if doc and doc.audio_path:
            self._save(doc.audio_path, "podcast audio")

    def _save_script(self) -> None:
        doc = self.selected()
        if doc:
            self._save(doc.path, "podcast script")


def main() -> None:
    default_dir = Path(__file__).resolve().parent.parent / "output" / "podcasts"
    parser = argparse.ArgumentParser(description="Play and read generated podcasts")
    parser.add_argument("--podcast-dir", type=Path, default=default_dir)
    args = parser.parse_args()
    if not args.podcast_dir.is_dir():
        raise SystemExit(f"Podcast folder not found: {args.podcast_dir}")
    PodcastApp(args.podcast_dir).mainloop()


if __name__ == "__main__":
    main()
