# AI Audio Overview Generator

Generate podcast-style audio overviews from documents using multiple LLM providers (Ollama, OpenAI, Claude) with RAG and Kokoro TTS.

## Features

- Create podcast scripts with natural dialogue
- Multi-speaker conversations with different voices
- Emotional cues for voice variety
- Convert to audio using Kokoro TTS
- Configurable duration and style
- Support for multiple LLM providers

## Usage

### Using Ollama (Local)

```bash
python python/ollama_learning/audio.py \
  --input input/classical_chinese \
  --topic "Ancient Chinese philosophy" \
  --output output/podcast.mp3 \
  --duration 10 \
  --style educational \
  --format mp3 \
  --provider ollama \
  --model qwen2.5
```

### Using OpenAI

```bash
python python/ollama_learning/audio.py \
  --input input/classical_chinese \
  --topic "Ancient Chinese philosophy" \
  --output output/podcast.mp3 \
  --duration 10 \
  --style educational \
  --format mp3 \
  --provider openai \
  --model gpt-4 \
  --api-key YOUR_OPENAI_API_KEY
```

### Using Claude

```bash
python python/ollama_learning/audio.py \
  --input input/classical_chinese \
  --topic "Ancient Chinese philosophy" \
  --output output/podcast.mp3 \
  --duration 10 \
  --style educational \
  --format mp3 \
  --provider claude \
  --model claude-3-5-sonnet-20241022 \
  --api-key YOUR_ANTHROPIC_API_KEY
```

## Parameters

- `--input`: Input folder containing text documents (*.txt)
- `--topic`: Podcast topic
- `--output`: Output audio file path
- `--duration`: Target duration in minutes (default: 10)
- `--style`: Podcast style (educational, conversational, debate, interview)
- `--format`: Audio format (mp3, wav)
- `--provider`: LLM provider (ollama, openai, claude)
- `--model`: Model to use
- `--embedding-model`: Embedding model (provider-specific)
- `--api-key`: API key for OpenAI/Claude
- `--json-only`: Only generate JSON script, not audio

## Provider Requirements

### Ollama
- Ollama running locally (http://localhost:11434)
- Required models: qwen2.5, gemma2, or similar
- Embedding model: embeddinggemma or qwen3-embedding

### OpenAI
- OpenAI API key
- Model: gpt-4, gpt-4-turbo, gpt-3.5-turbo
- Embedding: text-embedding-3-small (automatic)

### Claude
- Anthropic API key
- Model: claude-3-5-sonnet-20241022 recommended
- Note: Claude doesn't support embeddings, RAG will be disabled

## Podcast Structure

Generated podcasts include:
- Engaging title
- 2+ speakers with different voices
- Natural dialogue flow
- Emotional direction for voice variety
- Appropriate pauses and transitions
- Logical progression from intro to conclusion

## Voice Options

Kokoro provides various voice presets:
- `af_heart`: Female, warm
- `af_bella`: Female, professional
- `am_michael`: Male, professional
- `am_adam`: Male, deep
- And more (see Kokoro documentation)

## Audio Generation

The skill uses the existing Kokoro TTS system:
1. LLM generates structured podcast script
2. Script converted to Kokoro JSON format
3. Kokoro generates audio with different voices
4. FFmpeg encodes to final format

## Requirements

- For Ollama: Ollama running locally with required models
- For OpenAI: OpenAI API key
- For Claude: Anthropic API key
- Kokoro TTS installed (see requirements.txt)
- FFmpeg for audio encoding
- Kokoro voice models (downloaded on first use)

## Notes

- First run downloads Kokoro models (requires internet)
- GPU acceleration recommended for faster generation
- Use `--json-only` to generate script without audio
- Adjust duration based on content complexity