# Claude Code Generation

Use Anthropic's Claude 3.5 Sonnet (Claude Code) directly for advanced coding tasks, code analysis, and software engineering.

## Features

- Advanced code generation with Claude 3.5 Sonnet
- Code review and analysis
- Architecture design recommendations
- Security analysis and vulnerability detection
- Code explanation and documentation
- Multi-file project understanding
- Tool calling for complex workflows

## Usage

### Code Generation

Generate code with advanced reasoning:

```bash
python python/ollama_learning/claude_code.py \
  --provider claude \
  --model claude-3-5-sonnet-20241022 \
  --task "Design and implement a microservices architecture for an e-commerce platform" \
  --output output/ecommerce_architecture.py \
  --api-key YOUR_ANTHROPIC_API_KEY
```

### Code Review

Review and analyze code quality:

```bash
python python/ollama_learning/claude_code.py \
  --provider claude \
  --model claude-3-5-sonnet-20241022 \
  --task review \
  --input input/project/ \
  --output output/code_review.md \
  --api-key YOUR_ANTHROPIC_API_KEY
```

### Security Analysis

Analyze code for security vulnerabilities:

```bash
python python/ollama_learning/claude_code.py \
  --provider claude \
  --model claude-3-5-sonnet-20241022 \
  --task security \
  --input input/authentication.py \
  --output output/security_report.md \
  --api-key YOUR_ANTHROPIC_API_KEY
```

### Architecture Design

Design software architecture:

```bash
python python/ollama_learning/claude_code.py \
  --provider claude \
  --model claude-3-5-sonnet-20241022 \
  --task architecture \
  --description "Build a scalable real-time chat application" \
  --output output/architecture.md \
  --api-key YOUR_ANTHROPIC_API_KEY
```

### Code Explanation

Explain complex code:

```bash
python python/ollama_learning/claude_code.py \
  --provider claude \
  --model claude-3-5-sonnet-20241022 \
  --task explain \
  --input input/complex_algorithm.py \
  --output output/explanation.md \
  --api-key YOUR_ANTHROPIC_API_KEY
```

### Multi-File Analysis

Analyze entire project structure:

```bash
python python/ollama_learning/claude_code.py \
  --provider claude \
  --model claude-3-5-sonnet-20241022 \
  --task analyze \
  --input input/my_project/ \
  --output output/project_analysis.md \
  --api-key YOUR_ANTHROPIC_API_KEY
```

## Parameters

- `--provider`: Must be "claude" for Claude Code
- `--model`: Claude model (claude-3-5-sonnet-20241022 recommended for coding)
- `--task`: Task type (generate, review, security, architecture, explain, analyze)
- `--input`: Input file or directory
- `--description`: Natural language description (for generate/architecture)
- `--output`: Output file path
- `--api-key`: Anthropic API key
- `--language`: Programming language
- `--focus`: Analysis focus (performance, security, maintainability, etc.)

## Supported Models

- `claude-3-5-sonnet-20241022` - Best for coding (Claude Code)
- `claude-3-5-haiku-20241022` - Faster, good for quick tasks
- `claude-3-opus-20240229` - Most capable, slower

## Task Types

### Generate
Create new code from descriptions with best practices and patterns.

### Review
Analyze code quality, suggest improvements, identify issues.

### Security
Security-focused analysis, vulnerability detection, secure coding practices.

### Architecture
Design system architecture, recommend patterns and technologies.

### Explain
Provide detailed explanations of code logic and design decisions.

### Analyze
Comprehensive project analysis including dependencies, structure, and recommendations.

## Analysis Focus Options

- `performance` - Performance optimization opportunities
- `security` - Security vulnerabilities and best practices
- `maintainability` - Code maintainability and technical debt
- `scalability` - Scalability and architecture patterns
- `testing` - Test coverage and testing strategies
- `documentation` - Documentation quality and completeness

## API Key Setup

Set your Anthropic API key:

```bash
# Set environment variable
export ANTHROPIC_API_KEY="your-api-key"

# Or pass via command line
--api-key your-api-key
```

## Examples

### Full Stack Application

```bash
python python/ollama_learning/claude_code.py \
  --provider claude \
  --model claude-3-5-sonnet-20241022 \
  --task "Create a full-stack application with React frontend, FastAPI backend, PostgreSQL database, and Docker deployment" \
  --output output/fullstack_app/ \
  --api-key YOUR_ANTHROPIC_API_KEY
```

### Legacy Code Migration

```bash
python python/ollama_learning/claude_code.py \
  --provider claude \
  --model claude-3-5-sonnet-20241022 \
  --task migrate \
  --input input/legacy_python2/ \
  --target modern_python3 \
  --output output/migrated_code/ \
  --api-key YOUR_ANTHROPIC_API_KEY
```

### Performance Analysis

```bash
python python/ollama_learning/claude_code.py \
  --provider claude \
  --model claude-3-5-sonnet-20241022 \
  --task analyze \
  --input input/slow_service.py \
  --focus performance \
  --output output/performance_report.md \
  --api-key YOUR_ANTHROPIC_API_KEY
```

## Claude Code Advantages

- **Strong Reasoning**: Excellent at understanding complex requirements
- **Security Focused**: Built-in safety and security considerations
- **Long Context**: Can analyze large codebases and multiple files
- **Tool Calling**: Can use tools for complex workflows
- **Explanation Quality**: Provides clear, detailed explanations

## Requirements

- Anthropic API key
- Anthropic Python package
- For large projects: Sufficient context window (Claude 3.5 Sonnet has 200K tokens)

## Best Practices

1. **Provide Context**: Include relevant files and project structure
2. **Specify Constraints**: Mention performance, security, or scalability requirements
3. **Iterative Approach**: Use Claude's strong reasoning for iterative refinement
4. **Security First**: Leverage Claude's security focus for sensitive code
5. **Multi-Step Tasks**: Break complex tasks into smaller steps

## Limitations

- Claude doesn't provide embeddings (RAG disabled for Claude provider)
- API rate limits apply
- Large codebases may require multiple analyses
- No direct code execution (requires manual testing)

## Notes

- Claude 3.5 Sonnet is optimized for coding tasks
- Use Claude Opus for the most complex reasoning tasks
- Claude Haiku for quick, simple tasks
- Always review and test generated code
- Consider security implications for sensitive applications