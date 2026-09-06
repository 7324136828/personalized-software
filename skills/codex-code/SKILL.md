# Codex Code Generation

Use OpenAI's Codex models (GPT-4 for coding) directly for code generation, debugging, and programming tasks.

## Features

- Direct integration with OpenAI's coding models
- Code generation from natural language descriptions
- Code debugging and error fixing
- Code refactoring and optimization
- Documentation generation
- Unit test generation

## Usage

### Code Generation

Generate code from descriptions:

```bash
python python/ollama_learning/codex.py \
  --provider openai \
  --model gpt-4 \
  --task "Write a Python function to calculate fibonacci numbers" \
  --output output/fibonacci.py \
  --api-key YOUR_OPENAI_API_KEY
```

### Code Debugging

Debug existing code:

```bash
python python/ollama_learning/codex.py \
  --provider openai \
  --model gpt-4 \
  --task debug \
  --input input/broken_code.py \
  --output output/fixed_code.py \
  --api-key YOUR_OPENAI_API_KEY
```

### Code Refactoring

Refactor and optimize code:

```bash
python python/ollama_learning/codex.py \
  --provider openai \
  --model gpt-4 \
  --task refactor \
  --input input/legacy_code.py \
  --output output/refactored_code.py \
  --api-key YOUR_OPENAI_API_KEY
```

### Documentation Generation

Generate documentation for code:

```bash
python python/ollama_learning/codex.py \
  --provider openai \
  --model gpt-4 \
  --task document \
  --input input/project.py \
  --output output/docs.md \
  --api-key YOUR_OPENAI_API_KEY
```

### Test Generation

Generate unit tests:

```bash
python python/ollama_learning/codex.py \
  --provider openai \
  --model gpt-4 \
  --task test \
  --input input/module.py \
  --output output/test_module.py \
  --api-key YOUR_OPENAI_API_KEY
```

## Parameters

- `--provider`: Must be "openai" for Codex
- `--model`: OpenAI coding model (gpt-4, gpt-4-turbo, gpt-3.5-turbo)
- `--task`: Task type (generate, debug, refactor, document, test)
- `--input`: Input code file (for debug/refactor/document/test)
- `--output`: Output file path
- `--api-key`: OpenAI API key
- `--language`: Programming language (auto-detected if not specified)
- `--style`: Code style (PEP8, Google, functional, etc.)

## Supported Models

- `gpt-4` - Best for complex coding tasks
- `gpt-4-turbo` - Faster, good for most tasks
- `gpt-3.5-turbo` - Fastest, good for simple tasks

## Code Style Options

- `PEP8` - Python PEP 8 style
- `Google` - Google Python Style Guide
- `functional` - Functional programming style
- `OOP` - Object-oriented style
- `minimal` - Minimal, concise code

## Best Practices

1. **Be Specific**: Provide clear, detailed descriptions for code generation
2. **Include Context**: For debugging, include error messages and expected behavior
3. **Specify Requirements**: Mention libraries, frameworks, and constraints
4. **Review Output**: Always review and test generated code
5. **Iterate**: Use refactoring to improve initial generations

## API Key Setup

Set your OpenAI API key:

```bash
# Set environment variable
export OPENAI_API_KEY="your-api-key"

# Or pass via command line
--api-key your-api-key
```

## Examples

### Generate a REST API

```bash
python python/ollama_learning/codex.py \
  --provider openai \
  --model gpt-4 \
  --task "Create a FastAPI REST endpoint for user management with CRUD operations" \
  --output output/user_api.py \
  --api-key YOUR_OPENAI_API_KEY
```

### Debug with Error Context

```bash
python python/ollama_learning/codex.py \
  --provider openai \
  --model gpt-4 \
  --task debug \
  --input input/error_code.py \
  --error "TypeError: 'NoneType' object is not subscriptable at line 42" \
  --output output/fixed_code.py \
  --api-key YOUR_OPENAI_API_KEY
```

## Requirements

- OpenAI API key
- OpenAI Python package
- For Python tasks: Python 3.7+

## Notes

- Codex excels at Python, JavaScript, TypeScript, and many other languages
- Generated code should always be reviewed and tested
- Complex tasks may require multiple iterations
- Use appropriate model based on task complexity