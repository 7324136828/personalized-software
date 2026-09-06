# AI Quiz Generator

Generate interactive quizzes from documents using multiple LLM providers (Ollama, OpenAI, Claude) with RAG.

## Features

- Create multiple-choice quizzes from source documents
- Difficulty levels based on Bloom's taxonomy
- Interactive GUI for taking quizzes
- Detailed explanations for each answer
- Score tracking and results
- Support for multiple LLM providers

## Usage

### Using Ollama (Local)

```bash
python python/ollama_learning/quiz.py \
  --input input/news \
  --topic "economic indicators" \
  --output output/quiz.json \
  --count 10 \
  --difficulty understanding \
  --interactive \
  --provider ollama \
  --model qwen2.5
```

### Using OpenAI

```bash
python python/ollama_learning/quiz.py \
  --input input/news \
  --topic "economic indicators" \
  --output output/quiz.json \
  --count 10 \
  --difficulty understanding \
  --interactive \
  --provider openai \
  --model gpt-4 \
  --api-key YOUR_OPENAI_API_KEY
```

### Using Claude

```bash
python python/ollama_learning/quiz.py \
  --input input/news \
  --topic "economic indicators" \
  --output output/quiz.json \
  --count 10 \
  --difficulty understanding \
  --interactive \
  --provider claude \
  --model claude-3-5-sonnet-20241022 \
  --api-key YOUR_ANTHROPIC_API_KEY
```

## Parameters

- `--input`: Input folder containing text documents (*.txt)
- `--topic`: Quiz topic
- `--output`: Output file path
- `--count`: Number of questions to generate (default: 10)
- `--difficulty`: Question difficulty (recall, understanding, application, analysis, expert)
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

## Difficulty Levels

- **Recall**: Basic factual recall
- **Understanding**: Comprehension and explanation
- **Application**: Applying concepts to new situations
- **Analysis**: Breaking down complex ideas
- **Expert**: Synthesis and evaluation

## Interactive GUI Features

- Multiple choice selection
- Immediate feedback with explanations
- Score tracking
- Progress bar
- Final results with performance assessment
- Keyboard navigation (arrow keys, space)

## Requirements

- For Ollama: Ollama running locally with required models
- For OpenAI: OpenAI API key
- For Claude: Anthropic API key