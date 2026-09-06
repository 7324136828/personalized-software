# Multi-LLM Learning System

A comprehensive AI learning system that supports multiple LLM providers (Ollama, OpenAI, Claude) to generate educational content from documents. Features include reports, flashcards, quizzes, free-text Q&A, mind maps, slide decks, audio podcasts, data table extraction, and advanced coding assistance with Codex and Claude Code.

## Quick Start (React viewers)

A batch script at the repository root builds the React viewers and starts a
local Python backend that serves generated content directly from `output/`:

```bat
run.bat
```

It installs dependencies on first run, builds for production, serves on
http://localhost:4173, and opens the Q&A view. Use `run.bat dev` for hot reload,
`run.bat build` to build without serving, or `run.bat help` for all options.
No `npm run sync` step is needed. See `react/README.md` for details.

## Features

### Educational Content Generation
- **Reports**: Generate comprehensive reports with citations
- **Flashcards**: Interactive flashcard system with GUI viewer
- **Quizzes**: Multiple-choice quizzes with interactive testing
- **Free-text Q&A**: Prompted written responses with temporary autosave and JSON download
- **Mind Maps**: Hierarchical concept maps
- **Slide Decks**: Presentation slides with GUI viewer
- **Audio Overviews**: Podcast-style audio generation with Kokoro TTS
- **Data Tables**: Structured data extraction
- **Infographics**: Visual one-page summaries with HTML export

### Advanced Coding Assistance
- **Codex**: OpenAI's coding models for code generation, debugging, and refactoring
- **Claude Code**: Advanced coding tasks with Claude 3.5 Sonnet including architecture design, security analysis, and code review

### Multi-LLM Provider Support
- **Ollama**: Local, free, privacy-focused (requires local installation)
- **OpenAI**: Cloud-based, high quality, structured output support (requires API key)
- **Claude**: Advanced reasoning, long context, security-focused (requires API key)

## Architecture

The system follows a SOURCE → RAG → OLLAMA → JSON → RENDERER architecture:

1. **Source**: Documents in the input folder
2. **RAG**: Document ingestion, chunking, and vector embeddings
3. **Ollama**: Local LLM for reasoning and structured JSON generation
4. **JSON**: Structured output using Pydantic schemas
5. **Renderer**: Python code renders the final output (GUI, files, etc.)

## Prerequisites

Choose one or more LLM providers to use:

### Option 1: Ollama (Local, Free)

#### 1. Ollama Installation

Download and install Ollama from [ollama.com](https://ollama.com)

#### 2. Install Required Models

```bash
# Pull a generation model (choose one)
ollama pull qwen2.5
# or
ollama pull gemma2
# or
ollama pull llama3.2

# Pull an embedding model
ollama pull embeddinggemma
# or
ollama pull qwen3-embedding
```

#### 3. Start Ollama

```bash
ollama serve
```

Ollama will be available at `http://localhost:11434`

### Option 2: OpenAI (Cloud, API Key Required)

#### 1. Get API Key

Sign up at [openai.com](https://openai.com) and get your API key

#### 2. Set Environment Variable

```bash
export OPENAI_API_KEY="your-api-key"
```

OpenAI supports structured output and embeddings natively.

### Option 3: Claude (Cloud, API Key Required)

#### 1. Get API Key

Sign up at [anthropic.com](https://anthropic.com) and get your API key

#### 2. Set Environment Variable

```bash
export ANTHROPIC_API_KEY="your-api-key"
```

Note: Claude doesn't provide embeddings API, so RAG features will be disabled when using Claude.

### Option 4: Use Multiple Providers

You can use different providers for different tasks. Each command accepts a `--provider` flag.

## Installation

With Python 3.11+ installed, the setup command creates `.venv`, installs both
Python and React dependencies, and runs the backend tests plus React checks.
`setup.bat` is a one-line wrapper around `setup_environment.py`:

```bat
setup.bat
```

The cross-platform equivalent is `python setup_environment.py`.

Use `setup.bat --skip-verify` when you only want to install or refresh
dependencies. The equivalent manual setup is:

```bash
# Create and activate a local Python environment (Windows)
python -m venv .venv
.venv\Scripts\activate

# Install Python and React dependencies
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
cd react
npm install
```

On macOS or Linux, activate with `source .venv/bin/activate`. `run.bat` and the
React npm scripts automatically prefer the repository `.venv` when it exists.

The requirements file includes:
- Ollama support: `requests`
- OpenAI support: `openai`
- Claude support: `anthropic`
- Core functionality: `pydantic`, `pandas`, `openpyxl`
- Audio generation: `kokoro`, `numpy`, `imageio-ffmpeg`

## Project Structure

```
├── input/                  # Place your documents here
│   ├── dataset1/
│   │   ├── document1.txt
│   │   └── document2.txt
│   └── dataset2/
│       └── document3.txt
├── output/                 # Generated content will be saved here
├── python/
│   ├── ollama_learning/   # Main package
│   │   ├── ollama_client.py
│   │   ├── rag_system.py
│   │   ├── schemas.py
│   │   ├── reports.py
│   │   ├── flashcards.py
│   │   ├── quiz.py
│   │   ├── mindmap.py
│   │   ├── infographic.py
│   │   ├── slides.py
│   │   ├── audio.py
│   │   └── datatable.py
│   └── podcast.py         # Existing Kokoro podcast generator
├── skills/                # Devin skill definitions
│   ├── ollama-reports/
│   ├── ollama-flashcards/
│   ├── ollama-quiz/
│   ├── ollama-mindmap/
│   ├── ollama-slides/
│   ├── ollama-audio/
│   ├── ollama-datatable/
│   └── ollama-infographic/
└── requirements.txt
```

## Usage

All commands support three providers via the `--provider` flag:
- `--provider ollama` (default): Local, free
- `--provider openai`: Cloud, requires `--api-key`
- `--provider claude`: Cloud, requires `--api-key`

### Reports

Generate a comprehensive report on a topic:

**Using Ollama (Local):**
```bash
python python/ollama_learning/reports.py \
  --input input/dataset1 \
  --topic "climate change impacts" \
  --output output/climate_report.md \
  --format markdown \
  --provider ollama \
  --model qwen2.5
```

**Using OpenAI:**
```bash
python python/ollama_learning/reports.py \
  --input input/dataset1 \
  --topic "climate change impacts" \
  --output output/climate_report.md \
  --format markdown \
  --provider openai \
  --model gpt-4 \
  --api-key YOUR_OPENAI_API_KEY
```

**Using Claude:**
```bash
python python/ollama_learning/reports.py \
  --input input/dataset1 \
  --topic "climate change impacts" \
  --output output/climate_report.md \
  --format markdown \
  --provider claude \
  --model claude-3-5-sonnet-20241022 \
  --api-key YOUR_ANTHROPIC_API_KEY
```

### Flashcards

Generate interactive flashcards:

```bash
python python/ollama_learning/flashcards.py \
  --input input/dataset1 \
  --topic "key concepts" \
  --output output/flashcards.json \
  --count 20 \
  --interactive \
  --provider ollama \
  --model qwen2.5
```

### Quizzes

Create a multiple-choice quiz:

```bash
python python/ollama_learning/quiz.py \
  --input input/dataset1 \
  --topic "subject matter" \
  --output output/quiz.json \
  --count 10 \
  --difficulty understanding \
  --interactive \
  --provider ollama \
  --model qwen2.5
```

### Free-text Q&A

Generate open-ended prompts that learners answer in their own words:

```bash
python -m python.ollama_learning.qanda \
  --input input/dataset1 \
  --topic "reflection and application" \
  --output output/qandas/reflection.json \
  --count 8 \
  --provider ollama \
  --model qwen2.5
```

Start `run.bat dev`, open the **Q&A** tab, and select the generated set.
Responses autosave to the Python backend's temporary directory and can be
downloaded as JSON during or after the session.

The matching desktop launcher reads and writes the same Q&A/session formats:

```bash
python python/qanda_launcher.py --qanda-dir output/qandas
```

### Mind Maps

Generate hierarchical mind maps:

```bash
python python/ollama_learning/mindmap.py \
  --input input/dataset1 \
  --topic "main topic" \
  --output output/mindmap.md \
  --format markdown \
  --max-depth 3 \
  --provider ollama \
  --model qwen2.5
```

### Slide Decks

Create presentation slides:

```bash
python python/ollama_learning/slides.py \
  --input input/dataset1 \
  --topic "presentation topic" \
  --output output/presentation.json \
  --count 12 \
  --style professional \
  --interactive \
  --provider ollama \
  --model qwen2.5
```

### Audio Overviews

Generate podcast-style audio:

```bash
python python/ollama_learning/audio.py \
  --input input/dataset1 \
  --topic "discussion topic" \
  --output output/podcast.mp3 \
  --duration 10 \
  --style educational \
  --format mp3 \
  --provider ollama \
  --model qwen2.5
```

### Data Tables

Extract structured data:

```bash
# First create a fields.json file
cat > fields.json << EOF
[
  {"name": "company", "description": "Company name"},
  {"name": "revenue", "description": "Annual revenue"},
  {"name": "year", "description": "Fiscal year"}
]
EOF

# Then extract data
python python/ollama_learning/datatable.py \
  --input input/dataset1 \
  --topic "financial data" \
  --output output/data.csv \
  --fields fields.json \
  --format csv \
  --provider ollama \
  --model qwen2.5
```

## Advanced Coding Assistance


### Infographics

Create a visual one-page summary:

```bash
python python/ollama_learning/infographic.py \
  --input input/classical_chinese \
  --topic "how the five texts differ" \
  --output output/infographic.html \
  --format html \
  --sections 6 \
  --provider ollama \
  --model qwen2.5
```

Formats: `html` (self-contained page), `markdown`, `json`. Section types are
`stat`, `chart`, `flow`, `comparison`, and `quote`; chart magnitudes are written
into the item strings as `Label: number`.

### Codex (OpenAI)

Use OpenAI's coding models for advanced programming tasks:

**Code Generation:**
```bash
python python/ollama_learning/codex.py \
  --task generate \
  --description "Write a Python function to calculate fibonacci numbers" \
  --output output/fibonacci.py \
  --api-key YOUR_OPENAI_API_KEY
```

**Code Debugging:**
```bash
python python/ollama_learning/codex.py \
  --task debug \
  --input input/broken_code.py \
  --error "TypeError at line 42" \
  --output output/fixed_code.py \
  --api-key YOUR_OPENAI_API_KEY
```

**Code Refactoring:**
```bash
python python/ollama_learning/codex.py \
  --task refactor \
  --input input/legacy_code.py \
  --output output/refactored_code.py \
  --api-key YOUR_OPENAI_API_KEY
```

**Test Generation:**
```bash
python python/ollama_learning/codex.py \
  --task test \
  --input input/module.py \
  --output output/test_module.py \
  --api-key YOUR_OPENAI_API_KEY
```

### Claude Code

Use Claude 3.5 Sonnet for advanced software engineering:

**Code Review:**
```bash
python python/ollama_learning/claude_code.py \
  --task review \
  --input input/project/ \
  --output output/code_review.md \
  --api-key YOUR_ANTHROPIC_API_KEY
```

**Security Analysis:**
```bash
python python/ollama_learning/claude_code.py \
  --task security \
  --input input/authentication.py \
  --output output/security_report.md \
  --api-key YOUR_ANTHROPIC_API_KEY
```

**Architecture Design:**
```bash
python python/ollama_learning/claude_code.py \
  --task architecture \
  --description "Design a microservices architecture for e-commerce" \
  --output output/architecture.md \
  --api-key YOUR_ANTHROPIC_API_KEY
```

**Project Analysis:**
```bash
python python/ollama_learning/claude_code.py \
  --task analyze \
  --input input/my_project/ \
  --focus performance \
  --output output/analysis.md \
  --api-key YOUR_ANTHROPIC_API_KEY
```

### Quizzes

Create a multiple-choice quiz:

```bash
python python/ollama_learning/quiz.py \
  --input input/dataset1 \
  --topic "subject matter" \
  --output output/quiz.json \
  --count 10 \
  --difficulty understanding \
  --interactive \
  --model qwen2.5
```

### Mind Maps

Generate hierarchical mind maps:

```bash
python python/ollama_learning/mindmap.py \
  --input input/dataset1 \
  --topic "main topic" \
  --output output/mindmap.md \
  --format markdown \
  --max-depth 3 \
  --model qwen2.5
```

### Slide Decks

Create presentation slides:

```bash
python python/ollama_learning/slides.py \
  --input input/dataset1 \
  --topic "presentation topic" \
  --output output/presentation.json \
  --count 12 \
  --style professional \
  --interactive \
  --model qwen2.5
```

### Audio Overviews

Generate podcast-style audio:

```bash
python python/ollama_learning/audio.py \
  --input input/dataset1 \
  --topic "discussion topic" \
  --output output/podcast.mp3 \
  --duration 10 \
  --style educational \
  --format mp3 \
  --model qwen2.5
```

### Data Tables

Extract structured data:

```bash
# First create a fields.json file
cat > fields.json << EOF
[
  {"name": "company", "description": "Company name"},
  {"name": "revenue", "description": "Annual revenue"},
  {"name": "year", "description": "Fiscal year"}
]
EOF

# Then extract data
python python/ollama_learning/datatable.py \
  --input input/dataset1 \
  --topic "financial data" \
  --output output/data.csv \
  --fields fields.json \
  --format csv \
  --model qwen2.5
```

## Interactive GUIs

Open the desktop viewer hub and choose any available content type:

```bash
python python/launcher_common.py
```

Use `--list` to inspect availability without opening a window, or
`--launch qanda` (and the other listed names) to open a viewer directly.

Flashcards, quizzes, Q&A sets, and slide decks include interactive controls:

- **Flashcards**: Space to flip, arrows to navigate
- **Quizzes**: Multiple choice with immediate feedback
- **Q&A**: Free-text responses with temporary autosave and JSON export
- **Slides**: Arrow keys to navigate, space for notes

Use the `--interactive` flag to launch the GUI.

## Model Selection

### Ollama Models

**Generation Models:**
- `qwen2.5` - Excellent for structured outputs
- `gemma2` - Good balance of speed and quality
- `llama3.2` - Strong reasoning capabilities

**Embedding Models:**
- `embeddinggemma` - Fast, good quality
- `qwen3-embedding` - Multilingual support

### OpenAI Models

**Generation Models:**
- `gpt-4` - Best quality, most capable
- `gpt-4-turbo` - Faster, good for most tasks
- `gpt-3.5-turbo` - Fastest, good for simple tasks

**Embedding Models:**
- `text-embedding-3-small` - Fast, cost-effective (automatic)
- `text-embedding-3-large` - Higher quality (optional)

### Claude Models

**Generation Models:**
- `claude-3-5-sonnet-20241022` - Best for coding (Claude Code)
- `claude-3-5-haiku-20241022` - Faster, good for quick tasks
- `claude-3-opus-20240229` - Most capable, slower

**Note:** Claude doesn't provide embeddings API. RAG features will be disabled when using Claude.

## Configuration

### RAG System

The RAG system uses:
- **Chunk size**: 500 words (configurable)
- **Chunk overlap**: 50 words
- **Embedding model**: Provider-specific (auto-selected)
- **Vector storage**: SQLite with cosine similarity

### Provider Connection

**Ollama:** Default URL: `http://localhost:11434`

**OpenAI:** Requires API key via `--api-key` or environment variable `OPENAI_API_KEY`

**Claude:** Requires API key via `--api-key` or environment variable `ANTHROPIC_API_KEY`

### Unified Client Interface

The system uses a unified client interface via `create_client()`:

```python
from ollama_learning import create_client

# Ollama
client = create_client("ollama", "qwen2.5")

# OpenAI
client = create_client("openai", "gpt-4", api_key="your-key")

# Claude
client = create_client("claude", "claude-3-5-sonnet-20241022", api_key="your-key")
```

## Devin Skills

Each feature has a corresponding Devin skill in the `skills/` directory:

### Educational Content Skills
- `skills/ollama-reports/` - Report generation (multi-provider)
- `skills/ollama-flashcards/` - Flashcard generation (multi-provider)
- `skills/ollama-quiz/` - Quiz generation (multi-provider)
- `skills/ollama-mindmap/` - Mind map generation (multi-provider)
- `skills/ollama-slides/` - Slide deck generation (multi-provider)
- `skills/ollama-audio/` - Audio overview generation (multi-provider)
- `skills/ollama-datatable/` - Data table extraction (multi-provider)
- `skills/ollama-infographic/` - Infographic generation (multi-provider)

### Advanced Coding Skills
- `skills/codex-code/` - OpenAI Codex for code generation, debugging, refactoring
- `skills/claude-code/` - Claude Code for advanced software engineering tasks

Use these skills directly from Devin for integrated workflow.

## Provider Comparison

| Feature | Ollama | OpenAI | Claude |
|---------|--------|--------|--------|
| **Cost** | Free (local) | Pay-per-use | Pay-per-use |
| **Privacy** | 100% local | Cloud | Cloud |
| **Embeddings** | Yes | Yes | No |
| **Structured Output** | Yes | Yes | Limited |
| **Context Window** | Medium | Large | Very Large |
| **Speed** | Depends on hardware | Fast | Fast |
| **Setup** | Local install | API key | API key |
| **Best For** | Privacy, cost | Quality, features | Reasoning, security |

## Troubleshooting

### Ollama Connection Issues

```bash
# Check if Ollama is running
curl http://localhost:11434/api/tags

# Start Ollama if not running
ollama serve
```

### OpenAI API Issues

```bash
# Check API key
echo $OPENAI_API_KEY

# Test connection
python -c "from openai import OpenAI; client = OpenAI(); print(client.models.list())"
```

### Claude API Issues

```bash
# Check API key
echo $ANTHROPIC_API_KEY

# Test connection
python -c "from anthropic import Anthropic; client = Anthropic(); print(client.messages.create(model='claude-3-5-haiku-20241022', max_tokens=10, messages=[{'role': 'user', 'content': 'Hi'}]))"
```

### Model Not Found

**Ollama:**
```bash
ollama list
ollama pull qwen2.5
ollama pull embeddinggemma
```

**OpenAI/Claude:** Check model name spelling and availability

### Import Errors

```bash
# Reinstall dependencies
pip install --upgrade -r requirements.txt
```

### RAG Disabled with Claude

This is expected - Claude doesn't provide embeddings. The system will work but without document retrieval.

### Audio Generation Issues

- Ensure FFmpeg is installed and in PATH
- Check Kokoro model downloads (first run requires internet)
- Use `--json-only` to generate script without audio

### Choosing the Right Provider

- **Use Ollama** for: Privacy-sensitive data, cost sensitivity, local processing
- **Use OpenAI** for: Best quality, structured output, embeddings required
- **Use Claude** for: Complex reasoning, long context, security analysis, when embeddings not needed

## Advanced Usage

### Python API

```python
from ollama_learning import create_client, RAGSystem, ReportGenerator

# Initialize with any provider
client = create_client("ollama", "qwen2.5")
# or
client = create_client("openai", "gpt-4", api_key="your-key")
# or
client = create_client("claude", "claude-3-5-sonnet-20241022", api_key="your-key")

# Initialize RAG (skip for Claude as it doesn't support embeddings)
try:
    rag = RAGSystem(client)
except NotImplementedError:
    print("RAG not supported for this provider (Claude)")
    rag = None

# Add documents (if RAG available)
if rag:
    rag.add_document_from_file(Path("input/document.txt"))

# Generate report
generator = ReportGenerator(client, rag)
report = generator.generate_report("topic")

# Save report
generator.save_report(report, Path("output/report.md"), "markdown")
```

### Codex Python API

```python
from ollama_learning import CodexAssistant

# Initialize
assistant = CodexAssistant(api_key="your-openai-key", model="gpt-4")

# Generate code
code = assistant.generate_code(
    description="Write a function to calculate fibonacci numbers",
    language="python"
)

# Debug code
fixed_code = assistant.debug_code(
    code=broken_code,
    error_message="TypeError at line 42"
)
```

### Claude Code Python API

```python
from ollama_learning import ClaudeCodeAssistant

# Initialize
assistant = ClaudeCodeAssistant(api_key="your-anthropic-key")

# Security analysis
security_report = assistant.security_analysis(
    code=auth_code,
    threat_model="web-application"
)

# Architecture design
architecture = assistant.design_architecture(
    description="Microservices for e-commerce platform",
    scale="large"
)

### Custom Schemas

Extend `schemas.py` to add custom structured output types:

```python
from pydantic import BaseModel, Field

class CustomOutput(BaseModel):
    field1: str = Field(..., description="Field description")
    field2: int = Field(..., description="Another field")
```

## Performance Tips

1. **Use GPU**: Ollama with GPU acceleration is much faster
2. **Batch Processing**: Process multiple documents at once
3. **Model Selection**: Smaller models (qwen2.5:7b) are faster
4. **Embedding Caching**: RAG system caches embeddings automatically

## License

This project is provided as-is for educational and research purposes.

## Contributing

Contributions are welcome! Please ensure:
- Code follows existing patterns
- New features include documentation
- Tests are added for new functionality
