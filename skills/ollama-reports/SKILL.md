# AI Reports Generator

Generate comprehensive reports from documents using multiple LLM providers (Ollama, OpenAI, Claude) with RAG (Retrieval-Augmented Generation).

## Features

- Ingest documents from the input folder
- Retrieve relevant context using vector embeddings
- Generate structured reports with citations
- Export to Markdown, JSON, or HTML formats
- Support for multiple LLM providers

## Usage

### Using Ollama (Local)

```bash
python python/ollama_learning/reports.py \
  --input input/news \
  --topic "climate change impacts" \
  --output output/climate_report.md \
  --format markdown \
  --provider ollama \
  --model qwen2.5
```

### Using OpenAI

```bash
python python/ollama_learning/reports.py \
  --input input/news \
  --topic "climate change impacts" \
  --output output/climate_report.md \
  --format markdown \
  --provider openai \
  --model gpt-4 \
  --api-key YOUR_OPENAI_API_KEY
```

### Using Claude

```bash
python python/ollama_learning/reports.py \
  --input input/news \
  --topic "climate change impacts" \
  --output output/climate_report.md \
  --format markdown \
  --provider claude \
  --model claude-3-5-sonnet-20241022 \
  --api-key YOUR_ANTHROPIC_API_KEY
```

## Parameters

- `--input`: Input folder containing text documents (*.txt)
- `--topic`: Report topic/question
- `--output`: Output file path
- `--format`: Output format (markdown, json, html)
- `--provider`: LLM provider (ollama, openai, claude)
- `--model`: Model to use
- `--embedding-model`: Embedding model (provider-specific)
- `--api-key`: API key for OpenAI/Claude

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

## Output

The skill generates a structured report with:
- Executive summary
- Multiple content sections
- Key claims with source citations
- Conclusions
- Source references

## Dataset Structure

Place your source documents in the input folder:
```
input/
  your_dataset/
    document1.txt
    document2.txt
    document3.txt
```