# AI Slide Deck Generator

Generate presentation slide decks from documents using multiple LLM providers (Ollama, OpenAI, Claude) with RAG and interactive GUI viewer.

## Features

- Create structured slide presentations from source documents
- Interactive GUI for viewing slides
- Export to JSON or Markdown formats
- Speaker notes and source citations
- Configurable slide count and style
- Support for multiple LLM providers

## Usage

### Using Ollama (Local)

```bash
python python/ollama_learning/slides.py \
  --input input/news \
  --topic "market analysis" \
  --output output/presentation.json \
  --count 12 \
  --style professional \
  --interactive \
  --provider ollama \
  --model qwen2.5
```

### Using OpenAI

```bash
python python/ollama_learning/slides.py \
  --input input/news \
  --topic "market analysis" \
  --output output/presentation.json \
  --count 12 \
  --style professional \
  --interactive \
  --provider openai \
  --model gpt-4 \
  --api-key YOUR_OPENAI_API_KEY
```

### Using Claude

```bash
python python/ollama_learning/slides.py \
  --input input/news \
  --topic "market analysis" \
  --output output/presentation.json \
  --count 12 \
  --style professional \
  --interactive \
  --provider claude \
  --model claude-3-5-sonnet-20241022 \
  --api-key YOUR_ANTHROPIC_API_KEY
```

## Parameters

- `--input`: Input folder containing text documents (*.txt)
- `--topic`: Presentation topic
- `--output`: Output file path
- `--count`: Number of slides to generate (default: 12)
- `--style`: Presentation style (professional, educational, executive)
- `--format`: Output format (json, markdown)
- `--provider`: LLM provider (ollama, openai, claude)
- `--model`: Model to use
- `--embedding-model`: Embedding model (provider-specific)
- `--api-key`: API key for OpenAI/Claude
- `--interactive`: Launch interactive GUI viewer

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

## Interactive GUI Features

- Navigate slides with arrow keys or buttons
- Toggle speaker notes with space bar
- Progress bar showing presentation progress
- Source citations display
- Full-screen presentation mode

## Slide Structure

Each slide includes:
- Clear title
- Optional subtitle
- 3-6 bullet points with key information
- Speaker notes for presenter
- Source references for citations
- Optional image query suggestions

## Presentation Styles

- **Professional**: Business-focused, concise, data-driven
- **Educational**: Teaching-focused, explanatory, examples
- **Executive**: High-level, strategic, summary-focused

## Requirements

- For Ollama: Ollama running locally with required models
- For OpenAI: OpenAI API key
- For Claude: Anthropic API key
- Python tkinter for GUI (included with Python)