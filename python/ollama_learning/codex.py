"""Codex code generation and programming tasks using OpenAI."""

import json
import logging
from pathlib import Path
from typing import Optional, List

from .client_interface import create_client

LOG = logging.getLogger(__name__)


class CodexAssistant:
    """Codex assistant for code generation and programming tasks."""
    
    def __init__(self, api_key: Optional[str] = None, model: str = "gpt-4"):
        self.client = create_client("openai", model, api_key=api_key)
        self.model = model
    
    def generate_code(
        self,
        description: str,
        language: str = "python",
        style: str = "PEP8",
        context: Optional[str] = None
    ) -> str:
        """Generate code from natural language description."""
        
        prompt = f"""Generate {language} code for the following task:

{description}

Requirements:
- Follow {style} style guidelines
- Include proper error handling
- Add docstrings and comments
- Make code production-ready
- Include type hints where applicable
"""

        if context:
            prompt += f"\nContext:\n{context}\n"
        
        response = self.client.generate(
            prompt=prompt,
            system="You are an expert programmer. Write clean, efficient, and well-documented code.",
            temperature=0.2  # Lower temperature for more deterministic code
        )
        
        return response
    
    def debug_code(
        self,
        code: str,
        error_message: Optional[str] = None,
        expected_behavior: Optional[str] = None
    ) -> str:
        """Debug and fix code issues."""
        
        prompt = f"""Debug the following code:

```python
{code}
```
"""
        
        if error_message:
            prompt += f"\nError message:\n{error_message}\n"
        
        if expected_behavior:
            prompt += f"\nExpected behavior:\n{expected_behavior}\n"
        
        prompt += """
Analyze the code, identify the issue, and provide the fixed version.
Explain what was wrong and how you fixed it.
"""
        
        response = self.client.generate(
            prompt=prompt,
            system="You are an expert debugger. Analyze code issues and provide fixes with explanations.",
            temperature=0.3
        )
        
        return response
    
    def refactor_code(
        self,
        code: str,
        goals: List[str] = None
    ) -> str:
        """Refactor code for improved quality."""
        
        if goals is None:
            goals = ["readability", "performance", "maintainability"]
        
        prompt = f"""Refactor the following code to improve: {', '.join(goals)}

```python
{code}
```

Provide:
1. The refactored code
2. Explanation of improvements made
3. Any trade-offs or considerations
"""
        
        response = self.client.generate(
            prompt=prompt,
            system="You are an expert code refactoring specialist. Improve code quality while maintaining functionality.",
            temperature=0.3
        )
        
        return response
    
    def generate_documentation(
        self,
        code: str,
        format: str = "markdown"
    ) -> str:
        """Generate documentation for code."""
        
        prompt = f"""Generate comprehensive documentation for the following code:

```python
{code}
```

Provide:
1. Overview and purpose
2. Function/class descriptions
3. Parameter explanations
4. Return value descriptions
5. Usage examples
6. Dependencies and requirements

Format: {format}
"""
        
        response = self.client.generate(
            prompt=prompt,
            system="You are a technical writer. Create clear, comprehensive documentation for code.",
            temperature=0.3
        )
        
        return response
    
    def generate_tests(
        self,
        code: str,
        test_framework: str = "pytest",
        coverage_target: str = "high"
    ) -> str:
        """Generate unit tests for code."""
        
        prompt = f"""Generate comprehensive unit tests for the following code using {test_framework}:

```python
{code}
```

Requirements:
- Target {coverage_target} coverage
- Test edge cases and error conditions
- Include both positive and negative test cases
- Use appropriate test fixtures and mocks
- Follow testing best practices

Provide:
1. Complete test file
2. Explanation of test strategy
3. Coverage recommendations
"""
        
        response = self.client.generate(
            prompt=prompt,
            system="You are a testing expert. Write comprehensive, well-structured unit tests.",
            temperature=0.3
        )
        
        return response
    
    def analyze_code(
        self,
        code: str,
        focus: str = "general"
    ) -> str:
        """Analyze code quality and provide recommendations."""
        
        prompt = f"""Analyze the following code with focus on {focus}:

```python
{code}
```

Provide:
1. Code quality assessment
2. Identified issues and recommendations
3. Best practices suggestions
4. Performance considerations
5. Security implications (if applicable)
"""
        
        response = self.client.generate(
            prompt=prompt,
            system="You are a code quality expert. Provide thorough analysis and actionable recommendations.",
            temperature=0.3
        )
        
        return response


def main():
    """CLI for Codex operations."""
    import argparse
    from pathlib import Path
    
    parser = argparse.ArgumentParser(description="Codex code generation and programming tasks")
    parser.add_argument("--task", choices=["generate", "debug", "refactor", "document", "test", "analyze"],
                       required=True, help="Task to perform")
    parser.add_argument("--input", type=Path, help="Input code file")
    parser.add_argument("--description", type=str, help="Natural language description")
    parser.add_argument("--output", type=Path, required=True, help="Output file path")
    parser.add_argument("--api-key", type=str, help="OpenAI API key")
    parser.add_argument("--model", type=str, default="gpt-4", help="OpenAI model")
    parser.add_argument("--language", type=str, default="python", help="Programming language")
    parser.add_argument("--style", type=str, default="PEP8", help="Code style")
    parser.add_argument("--error", type=str, help="Error message for debugging")
    parser.add_argument("--expected", type=str, help="Expected behavior for debugging")
    parser.add_argument("--format", type=str, default="markdown", help="Documentation format")
    parser.add_argument("--framework", type=str, default="pytest", help="Test framework")
    parser.add_argument("--focus", type=str, default="general", help="Analysis focus")
    
    args = parser.parse_args()
    
    logging.basicConfig(level=logging.INFO)
    
    # Initialize Codex assistant
    assistant = CodexAssistant(api_key=args.api_key, model=args.model)
    
    # Perform task
    if args.task == "generate":
        if not args.description:
            LOG.error("--description required for generate task")
            return 1
        
        code = assistant.generate_code(
            description=args.description,
            language=args.language,
            style=args.style
        )
    
    elif args.task == "debug":
        if not args.input or not args.input.exists():
            LOG.error("--input required for debug task")
            return 1
        
        input_code = args.input.read_text(encoding="utf-8")
        result = assistant.debug_code(
            code=input_code,
            error_message=args.error,
            expected_behavior=args.expected
        )
    
    elif args.task == "refactor":
        if not args.input or not args.input.exists():
            LOG.error("--input required for refactor task")
            return 1
        
        input_code = args.input.read_text(encoding="utf-8")
        result = assistant.refactor_code(code=input_code)
    
    elif args.task == "document":
        if not args.input or not args.input.exists():
            LOG.error("--input required for document task")
            return 1
        
        input_code = args.input.read_text(encoding="utf-8")
        result = assistant.generate_documentation(
            code=input_code,
            format=args.format
        )
    
    elif args.task == "test":
        if not args.input or not args.input.exists():
            LOG.error("--input required for test task")
            return 1
        
        input_code = args.input.read_text(encoding="utf-8")
        result = assistant.generate_tests(
            code=input_code,
            test_framework=args.framework
        )
    
    elif args.task == "analyze":
        if not args.input or not args.input.exists():
            LOG.error("--input required for analyze task")
            return 1
        
        input_code = args.input.read_text(encoding="utf-8")
        result = assistant.analyze_code(
            code=input_code,
            focus=args.focus
        )
    
    # Save output
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(result, encoding="utf-8")
    LOG.info(f"Saved output to {args.output}")
    
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())