---
name: podcast-json
description: Write or adapt conversational podcast scripts as JSON compatible with this repository's Kokoro generator. Use when a user provides a topic, article, notes, or an existing script and wants a podcast episode JSON or reusable podcast script template.
---

# Podcast JSON

Create a complete, spoken podcast script using the structure in
[assets/podcast.template.json](assets/podcast.template.json). The template supplies
field names and a suggested conversation flow; replace every `{{...}}` value with
finished content and expand or remove segments to fit the request.

For a prompt to paste into another language model, use
[references/generation-prompt.md](references/generation-prompt.md) together with
the JSON template. This folder is a repository skill and can be used by referring
to this file directly.

## Choose the episode content

- Follow the user's topic, source material, audience, duration, language, and cast.
  If unspecified, use accessible English, a roughly five-minute conversation,
  and the template's Maya/Daniel cast. These are defaults, not requirements.
- Maya (`maya`, `HOST_A`, `af_heart`) explains concepts calmly. Daniel (`daniel`,
  `HOST_B`, `am_michael`) asks useful questions, tests ideas, and offers examples.
  Both should contribute substance rather than repeat or praise each other.
- Adapt source material faithfully. Distinguish opinion and interpretation from
  factual claims; do not invent quotations, statistics, sources, or personal
  experiences. Preserve requested quotations and edits. If source material ends
  abruptly, do not fabricate its missing factual content; for a new adaptation,
  write a closing based on the material actually available.
- Use a brief hook and introductions, themed exchanges, practical takeaways when
  appropriate, and a complete closing. Avoid unfinished sentences, "the script
  continues" notes, and outlines standing in for dialogue.
- Write for listening: contractions, varied sentence lengths, concrete examples,
  and brief explanations of unfamiliar terms. Favor short exchanges over long
  uninterrupted essays. Do not force strict speaker alternation.
- Treat requested duration as approximate. Plan around 130-150 spoken words per
  minute, allowing for pauses. Count only dialogue; generated audio determines
  the actual duration. Do not label an estimate as a measured runtime.

## JSON contract

Generate one JSON object per episode. Use double-quoted strings, escape embedded
double quotes and newlines, and omit comments and trailing commas. Retain Unicode
punctuation. Do not put Markdown formatting, speaker labels, or stage directions
inside spoken dialogue.

| Location | Fields and constraints |
| --- | --- |
| Episode | `episode_title`: nonempty string; `podcast_show`: show-name string; `cast`: nonempty array; `script`: nonempty array. |
| Cast member | `speaker_id`: unique nonempty string; `host_id`: display label such as `HOST_A`; `name`: host name; `voice_file`: Kokoro voice name or existing local `.pt` file; `style`: descriptive string. |
| Segment | `segment_name`: nonempty string; `scenes`: array of scene objects in playback order. |
| Scene | `speaker_id`: exactly matches a cast member; `dialogue`: spoken string; `directions`: optional string. |

`host_id` and `name` describe the cast; playback selects voices by `speaker_id`
and `voice_file`. The show name is MP3 metadata and is not spoken automatically.
Include introductions or the show name in dialogue when they should be heard.
Use the supplied voice names unless the user selects others; do not invent voice
identifiers or nonexistent `.pt` paths. Relative `.pt` paths resolve beside the
episode JSON, not beside this skill.

The template targets American English (`--lang-code a`). Language is a renderer
CLI option, not a JSON field. For another language, use appropriate confirmed
voices and identify the needed CLI option in delivery notes if notes are allowed.
Do not put GPU settings, output paths, checkpoints, bitrate, music, or unsupported
per-scene speed fields in the episode JSON.

## Directions supported by main.py

- `[pause=400]` inserts 400 milliseconds **before** the scene's dialogue. Use a
  nonnegative integer; the total explicit pause within a scene must not exceed
  60000 ms. An explicit pause replaces the usual automatic gap.
- To pause after a turn, use a separate scene with the same `speaker_id`,
  `directions: "[pause=250]"`, and `dialogue: ""`. The pause carries forward to
  the next spoken turn or becomes trailing silence. Otherwise keep dialogue
  nonempty; the episode must contain spoken content.
- Automatic gaps are 250 ms on speaker changes and 800 ms between segments.
  Add explicit pauses only when they improve delivery.
- `[calm]`, `[upbeat]`, `[dramatic]`, and `[reflective]` adjust speech speed to
  0.96, 1.04, 0.90, and 0.93 times the base speed. Use at most one such cue per
  scene. A recognized scene cue overrides the cast's usual style keyword.
- Combine a cue and a pause as `"[reflective] [pause=400]"`. Directions are never
  spoken. Style changes affect pacing only; they do not guarantee emotion.
- The renderer also recognizes the word "pause" or "pauses" as a 350 ms pause
  when no explicit pause tag exists. Prefer explicit tags for predictable timing.
  Chuckles, laughter, music, applause, and SSML effects are not generated from
  directions, so do not rely on them to convey essential content.

## Deliver and check

When working in the repository, save each finished episode as
`input/<descriptive-name>.json` unless the user specifies another destination.
Choose a new filename for a new episode; preserve the target filename when asked
to update one. Keep templates, schemas, and notes out of `input/`, because the
renderer scans every JSON file there as an episode. For multiple episodes, write
separate files rather than a top-level array or concatenated JSON objects.

Validate a finished file from the project root:

```powershell
python main.py --input input/<descriptive-name>.json --dry-run
```

This checks the generator's input contract without downloading models, loading
CUDA, or generating audio. Also review the content: all speaker references must
resolve, placeholders must be replaced, and the episode must end naturally.
Only report validation as passed if the command actually succeeded. If execution
is unavailable, inspect JSON syntax and these constraints and state that limit
when delivery notes are permitted.

When returning an episode directly in chat, return only the JSON object unless
the user requests commentary or code fences. For repository file creation,
briefly report the path and validation result. Creating a script does not by
itself request audio synthesis.
