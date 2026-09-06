---
name: ollama-podcast
description: Generate source-grounded conversational podcast JSON with local Ollama and optionally render it to MP3 or WAV with this repository's Kokoro pipeline. Use for podcast creation from repository documents; do not use for unrelated audio editing or transcription.
---

# Ollama Podcast

Generate the script with Ollama, validate it against the renderer, and render
audio only when the user asks for audio or playback-ready output.

Before creating or adapting a script, read
[`../podcast-json/SKILL.md`](../podcast-json/SKILL.md). Its JSON contract,
supported directions, voice rules, and content guidance are authoritative.

## Generate from source documents

Use the repository generator so source text, the Ollama prompt, and output paths
stay consistent:

```powershell
python -m python.ollama_learning.audio `
  --input input/classical_chinese `
  --topic "Stillness, emptiness, and ethical life in Chinese classics" `
  --output output/podcasts/classical_chinese.mp3 `
  --duration 4 `
  --provider ollama `
  --model qwen2.5 `
  --device auto
```

Add `--json-only` when only a script is requested. The generator writes the
matching JSON beside the requested audio. For a hand-authored or adapted JSON
episode, save a durable example outside ignored generated-data folders and copy
it into `output/podcasts/` when it should appear in the GUIs.

## Validate and render existing JSON

```powershell
python python/podcasts.py --input output/podcasts/episode.json --dry-run
python python/podcasts.py --input output/podcasts/episode.json `
  --output output/podcasts/episode.mp3 --device auto
```

Keep the JSON and audio basename identical so the Python and React podcast
libraries associate them. Kokoro may download models on first synthesis; do not
claim that audio was generated unless the renderer completed successfully.
