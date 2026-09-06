# AI Mind Map Generator

Generate hierarchical mind maps from documents using multiple LLM providers (Ollama, OpenAI, Claude) with RAG.

## Features

- Create structured mind maps from source documents
- Hierarchical organization of concepts
- Export to multiple formats (Markdown, Mermaid, JSON)
- Visual representation of relationships
- Configurable depth levels
- Support for multiple LLM providers

## Usage

### Using Ollama (Local)

```bash
python python/ollama_learning/mindmap.py \
  --input input/classical_chinese \
  --topic "Chinese dynasties" \
  --output output/mindmap.md \
  --format markdown \
  --max-depth 3 \
  --provider ollama \
  --model qwen2.5
```

### Using OpenAI

```bash
python python/ollama_learning/mindmap.py \
  --input input/classical_chinese \
  --topic "Chinese dynasties" \
  --output output/mindmap.md \
  --format markdown \
  --max-depth 3 \
  --provider openai \
  --model gpt-4 \
  --api-key YOUR_OPENAI_API_KEY
```

### Using Claude

```bash
python python/ollama_learning/mindmap.py \
  --input input/classical_chinese \
  --topic "Chinese dynasties" \
  --output output/mindmap.md \
  --format markdown \
  --max-depth 3 \
  --provider claude \
  --model claude-3-5-sonnet-20241022 \
  --api-key YOUR_ANTHROPIC_API_KEY
```

## Parameters

- `--input`: Input folder containing text documents (*.txt)
- `--topic`: Mind map topic
- `--output`: Output file path
- `--format`: Output format (markdown, mermaid, json)
- `--provider`: LLM provider (ollama, openai, claude)
- `--model`: Model to use
- `--embedding-model`: Embedding model (provider-specific)
- `--api-key`: API key for OpenAI/Claude
- `--max-depth`: Maximum depth of mind map hierarchy (default: 3)

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

## Output Formats

- **Markdown**: Markmap-compatible format (can be rendered with Markmap)
- **Mermaid**: Mermaid diagram syntax (can be rendered in many tools)
- **JSON**: Structured data format for custom rendering

## Rendering Options

- **Markmap**: Install with `npm install -g markmap-cli`, then `markmap output.md`
- **Mermaid**: Use online editor at mermaid.live or integrate with documentation tools
- **Custom**: Use JSON output with your preferred visualization library

## Structure

Mind maps include:
- Central root node (main topic)
- Main branches (key categories)
- Sub-branches (specific details)
- Logical hierarchy from general to specific

## Requirements

- For Ollama: Ollama running locally with required models
- For OpenAI: OpenAI API key
- For Claude: Anthropic API key
- For rendering: Markmap CLI or Mermaid-compatible viewer