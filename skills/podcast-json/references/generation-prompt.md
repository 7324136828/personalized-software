# Prompt for a language model

In this repository, a short request is enough:

> Use skills/podcast-json/SKILL.md to create a roughly eight-minute podcast about
> how habits form for a general audience. Use Maya and Daniel, save the finished
> episode as input/habits.json, and validate it with main.py --dry-run.

For a model that cannot read this repository, attach or paste `SKILL.md` and
`assets/podcast.template.json`, then paste the prompt below. Replace the brief
fields with your own requirements; the topic examples are not fixed defaults.

```text
Create a complete podcast episode using the attached podcast-json instructions
and JSON template.

Topic or source material: [Paste the topic, article, or notes here]
Audience: [Who will listen and what they already know]
Target duration: [Approximate number of minutes]
Language: [American English, or your requested language]
Show name: [The Curious Machine, or your own show name]
Cast: [Maya / af_heart and Daniel / am_michael, or confirmed alternatives]
Tone: [For example, thoughtful, practical, and conversational]
Must cover: [Key questions, ideas, and examples]
Avoid: [Optional exclusions]

Adapt the number of segments and exchanges to the content and duration. Write
finished dialogue with a clear opening, substantive conversation, and a complete
closing. Ground factual claims in the supplied source material; do not invent
statistics, quotations, or references.

Return only one valid JSON object with episode_title, podcast_show, cast, and
script. Keep every speaker_id consistent with the cast. Put performance cues
only in directions, using the supported pacing cues and [pause=N] notation.
Replace every template placeholder. Do not include Markdown fences, comments,
an outline, an unfinished ending, or any text outside the JSON object.
```

Save the resulting object as a new `input/*.json` file and run:

```powershell
python main.py --input input/habits.json --dry-run
```

Use the actual saved filename in the command. Passing a syntax check does not
establish factual accuracy or guarantee the estimated duration; review the script
before generating the audio.
