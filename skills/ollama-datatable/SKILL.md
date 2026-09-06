# AI Data Table Extractor

Extract structured data tables from documents using multiple LLM providers (Ollama, OpenAI, Claude) with RAG.

## Features

- Extract structured data from source documents
- Define custom fields for extraction
- Export to CSV, Excel, or JSON formats
- Source tracking with citations
- Pandas DataFrame integration
- Support for multiple LLM providers

## Usage

### Using Ollama (Local)

```bash
python python/ollama_learning/datatable.py \
  --input input/news \
  --topic "company financials" \
  --output output/financial_data.csv \
  --fields fields.json \
  --format csv \
  --provider ollama \
  --model qwen2.5
```

### Using OpenAI

```bash
python python/ollama_learning/datatable.py \
  --input input/news \
  --topic "company financials" \
  --output output/financial_data.csv \
  --fields fields.json \
  --format csv \
  --provider openai \
  --model gpt-4 \
  --api-key YOUR_OPENAI_API_KEY
```

### Using Claude

```bash
python python/ollama_learning/datatable.py \
  --input input/news \
  --topic "company financials" \
  --output output/financial_data.csv \
  --fields fields.json \
  --format csv \
  --provider claude \
  --model claude-3-5-sonnet-20241022 \
  --api-key YOUR_ANTHROPIC_API_KEY
```

## Field Definitions

Create a JSON file defining fields to extract:

```json
[
  {
    "name": "company",
    "description": "Name of the company",
    "example": "Acme Corp"
  },
  {
    "name": "revenue",
    "description": "Annual revenue in millions",
    "example": "$500M"
  },
  {
    "name": "year",
    "description": "Fiscal year",
    "example": "2024"
  }
]
```

## Parameters

- `--input`: Input folder containing text documents (*.txt)
- `--topic`: Extraction topic/context
- `--output`: Output file path
- `--fields`: JSON file with field definitions or inline JSON string
- `--format`: Output format (json, csv, excel)
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

## Output Formats

- **CSV**: Comma-separated values (compatible with Excel, Google Sheets)
- **Excel**: .xlsx format with multiple sheets support
- **JSON**: Structured data for programmatic use

## Data Quality

The extractor:
- Uses lower temperature (0.3) for precise extraction
- Only extracts explicitly stated information
- Marks missing data as "N/A"
- Includes source document and page references
- Validates against field definitions

## Use Cases

- Extract study metadata from research papers
- Create company comparison tables
- Build product feature matrices
- Compile statistical data from reports
- Generate structured datasets from unstructured text

## Requirements

- For Ollama: Ollama running locally with required models
- For OpenAI: OpenAI API key
- For Claude: Anthropic API key
- Pandas for data manipulation
- OpenPyXL for Excel export