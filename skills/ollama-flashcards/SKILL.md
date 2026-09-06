# AI Flashcards Generator

Generate interactive flashcards from documents using multiple LLM providers (Ollama, OpenAI, Claude) with RAG.

## Features

- Create flashcards from source documents
- Multiple card types: basic, cloze, definition, concept
- Interactive GUI for studying
- Export to JSON or Anki format
- Tag-based categorization
- Support for multiple LLM providers

## Usage

### Using Ollama (Local)

```bash
python python/ollama_learning/flashcards.py \
  --input input/classical_chinese \
  --topic "Confucian philosophy" \
  --output output/flashcards.json \
  --count 20 \
  --interactive \
  --provider ollama \
  --model qwen2.5
```

### Using OpenAI

```bash
python python/ollama_learning/flashcards.py \
  --input input/classical_chinese \
  --topic "Confucian philosophy" \
  --output output/flashcards.json \
  --count 20 \
  --interactive \
  --provider openai \
  --model gpt-4 \
  --api-key YOUR_OPENAI_API_KEY
```

### Using Claude

```bash
python python/ollama_learning/flashcards.py \
  --input input/classical_chinese \
  --topic "Confucian philosophy" \
  --output output/flashcards.json \
  --count 20 \
  --interactive \
  --provider claude \
  --model claude-3-5-sonnet-20241022 \
  --api-key YOUR_ANTHROPIC_API_KEY
```

## Parameters

- `--input`: Input folder containing text documents (*.txt)
- `--topic`: Flashcard topic
- `--output`: Output file path
- `--count`: Number of flashcards to generate (default: 20)
- `--format`: Output format (json, anki)
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

- Navigate with arrow keys or buttons
- Space bar to flip cards
- Progress tracking
- Tag display
- Keyboard shortcuts for efficient studying

## Card Types

- **Basic**: Question on front, answer on back
- **Cloze**: Fill-in-the-blank using {{c1::answer}} format
- **Definition**: Term on front, definition on back
- **Concept**: Concept on front, explanation on back

## Requirements

- For Ollama: Ollama running locally with required models
- For OpenAI: OpenAI API key
- For Claude: Anthropic API key
- For Anki export: Anki desktop application