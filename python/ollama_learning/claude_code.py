"""Claude Code - Advanced coding tasks using Claude 3.5 Sonnet."""

import json
import logging
from pathlib import Path
from typing import Optional, List

from .client_interface import create_client

LOG = logging.getLogger(__name__)


class ClaudeCodeAssistant:
    """Claude Code assistant for advanced programming tasks."""
    
    def __init__(self, api_key: Optional[str] = None, model: str = "claude-3-5-sonnet-20241022"):
        self.client = create_client("claude", model, api_key=api_key)
        self.model = model
        self.is_claude_code = "sonnet" in model.lower()
    
    def generate_code(
        self,
        description: str,
        language: str = "python",
        context: Optional[str] = None,
        constraints: Optional[List[str]] = None
    ) -> str:
        """Generate code with advanced reasoning."""
        
        prompt = f"""Generate {language} code for the following task:

{description}
"""
        
        if context:
            prompt += f"\nContext:\n{context}\n"
        
        if constraints:
            prompt += f"\nConstraints:\n" + "\n".join(f"- {c}" for c in constraints)
        
        prompt += """
Provide:
1. Well-structured, production-ready code
2. Clear comments and documentation
3. Error handling and edge cases
4. Type hints where applicable
5. Usage examples
6. Explanation of design decisions
"""
        
        response = self.client.generate(
            prompt=prompt,
            system="You are Claude Code, an expert software engineer. Write clean, efficient, and well-documented code with strong reasoning about design decisions.",
            temperature=0.3
        )
        
        return response
    
    def review_code(
        self,
        code: str,
        focus: str = "general"
    ) -> str:
        """Review code with comprehensive analysis."""
        
        prompt = f"""Review the following code with focus on {focus}:

```python
{code}
```

Provide:
1. Overall assessment
2. Code quality issues
3. Security vulnerabilities (if any)
4. Performance considerations
5. Maintainability concerns
6. Best practices violations
7. Specific recommendations with examples
8. Priority of issues (critical, high, medium, low)
"""
        
        response = self.client.generate(
            prompt=prompt,
            system="You are Claude Code, an expert code reviewer. Provide thorough, actionable feedback with specific examples and prioritized recommendations.",
            temperature=0.3
        )
        
        return response
    
    def security_analysis(
        self,
        code: str,
        threat_model: Optional[str] = None
    ) -> str:
        """Perform security-focused code analysis."""
        
        prompt = f"""Perform a comprehensive security analysis of the following code:

```python
{code}
```
"""
        
        if threat_model:
            prompt += f"\nThreat model: {threat_model}\n"
        
        prompt += """
Provide:
1. Identified security vulnerabilities
2. Potential attack vectors
3. Data leakage risks
4. Authentication/authorization issues
5. Input validation problems
6. Dependency security concerns
7. Secure coding recommendations
8. Compliance considerations (GDPR, SOC2, etc.)
"""
        
        response = self.client.generate(
            prompt=prompt,
            system="You are Claude Code, a security expert. Identify vulnerabilities and provide secure coding recommendations with detailed explanations.",
            temperature=0.2
        )
        
        return response
    
    def design_architecture(
        self,
        description: str,
        constraints: Optional[List[str]] = None,
        scale: str = "medium"
    ) -> str:
        """Design software architecture."""
        
        prompt = f"""Design a software architecture for: {description}

Scale: {scale}
"""
        
        if constraints:
            prompt += f"\nConstraints:\n" + "\n".join(f"- {c}" for c in constraints)
        
        prompt += """
Provide:
1. High-level architecture diagram (text-based)
2. Component breakdown and responsibilities
3. Technology stack recommendations
4. Data flow and communication patterns
5. Scalability considerations
6. Security architecture
7. Deployment strategy
8. Trade-offs and alternatives
"""
        
        response = self.client.generate(
            prompt=prompt,
            system="You are Claude Code, a software architect. Design robust, scalable systems with clear rationale for architectural decisions.",
            temperature=0.4
        )
        
        return response
    
    def explain_code(
        self,
        code: str,
        detail_level: str = "comprehensive"
    ) -> str:
        """Explain code with varying detail levels."""
        
        prompt = f"""Explain the following code ({detail_level} detail):

```python
{code}
```

Provide:
1. High-level purpose and functionality
2. Step-by-step logic breakdown
3. Key design patterns used
4. Data structures and algorithms
5. Complexity analysis (time/space)
6. Potential edge cases
7. Usage examples
8. Common pitfalls
"""
        
        response = self.client.generate(
            prompt=prompt,
            system="You are Claude Code, an expert educator. Explain code clearly with appropriate depth, using analogies and examples when helpful.",
            temperature=0.3
        )
        
        return response
    
    def analyze_project(
        self,
        project_path: Path,
        focus: str = "general"
    ) -> str:
        """Analyze entire project structure."""
        
        # Collect project information
        project_info = self._collect_project_info(project_path)
        
        prompt = f"""Analyze the following project structure:

{project_info}

Focus: {focus}

Provide:
1. Project overview and purpose
2. Architecture assessment
3. Code organization evaluation
4. Dependency analysis
5. Potential technical debt
6. Scalability concerns
7. Security considerations
8. Improvement recommendations
"""
        
        response = self.client.generate(
            prompt=prompt,
            system="You are Claude Code, a software engineering expert. Analyze projects holistically and provide actionable recommendations.",
            temperature=0.3
        )
        
        return response
    
    def _collect_project_info(self, project_path: Path) -> str:
        """Collect information about project structure."""
        info_lines = [f"Project: {project_path.name}"]
        
        # Directory structure
        info_lines.append("\nDirectory Structure:")
        for item in sorted(project_path.rglob("*")):
            if item.is_file() and item.suffix in ['.py', '.js', '.ts', '.java', '.go', '.rs']:
                rel_path = item.relative_to(project_path)
                info_lines.append(f"  {rel_path}")
        
        # Sample files content (limit to avoid token limits)
        info_lines.append("\nSample File Contents:")
        code_files = list(project_path.rglob("*.py"))[:5]  # Limit to 5 files
        
        for file_path in code_files:
            try:
                content = file_path.read_text(encoding="utf-8")
                # Limit content per file
                if len(content) > 2000:
                    content = content[:2000] + "\n... (truncated)"
                info_lines.append(f"\n{file_path.relative_to(project_path)}:")
                info_lines.append("```")
                info_lines.append(content)
                info_lines.append("```")
            except Exception as e:
                info_lines.append(f"\n{file_path.relative_to(project_path)}: Error reading file: {e}")
        
        return "\n".join(info_lines)
    
    def migrate_code(
        self,
        code: str,
        source_language: str,
        target_language: str,
        preserve_behavior: bool = True
    ) -> str:
        """Migrate code between languages or versions."""
        
        prompt = f"""Migrate the following {source_language} code to {target_language}:

```{source_language}
{code}
```

Requirements:
- {"Preserve exact behavior" if preserve_behavior else "Improve while maintaining core functionality"}
- Use idiomatic {target_language} patterns
- Maintain code structure where possible
- Update for modern {target_language} best practices
- Add appropriate error handling
- Include type annotations if applicable

Provide:
1. Migrated code
2. Explanation of changes
3. Any behavioral differences
4. Additional improvements made
"""
        
        response = self.client.generate(
            prompt=prompt,
            system="You are Claude Code, a polyglot programmer. Migrate code between languages while preserving functionality and leveraging target language best practices.",
            temperature=0.3
        )
        
        return response


def main():
    """CLI for Claude Code operations."""
    import argparse
    from pathlib import Path
    
    parser = argparse.ArgumentParser(description="Claude Code - Advanced programming tasks")
    parser.add_argument("--task", choices=["generate", "review", "security", "architecture", "explain", "analyze", "migrate"],
                       required=True, help="Task to perform")
    parser.add_argument("--input", type=Path, help="Input file or directory")
    parser.add_argument("--description", type=str, help="Natural language description")
    parser.add_argument("--output", type=Path, required=True, help="Output file path")
    parser.add_argument("--api-key", type=str, help="Anthropic API key")
    parser.add_argument("--model", type=str, default="claude-3-5-sonnet-20241022", help="Claude model")
    parser.add_argument("--language", type=str, default="python", help="Programming language")
    parser.add_argument("--focus", type=str, default="general", help="Analysis focus")
    parser.add_argument("--detail", type=str, default="comprehensive", help="Explanation detail level")
    parser.add_argument("--scale", type=str, default="medium", help="Architecture scale")
    parser.add_argument("--threat-model", type=str, help="Security threat model")
    parser.add_argument("--source-lang", type=str, help="Source language for migration")
    parser.add_argument("--target-lang", type=str, help="Target language for migration")
    
    args = parser.parse_args()
    
    logging.basicConfig(level=logging.INFO)
    
    # Initialize Claude Code assistant
    assistant = ClaudeCodeAssistant(api_key=args.api_key, model=args.model)
    
    # Perform task
    if args.task == "generate":
        if not args.description:
            LOG.error("--description required for generate task")
            return 1
        
        result = assistant.generate_code(
            description=args.description,
            language=args.language
        )
    
    elif args.task == "review":
        if not args.input or not args.input.exists():
            LOG.error("--input required for review task")
            return 1
        
        input_code = args.input.read_text(encoding="utf-8")
        result = assistant.review_code(code=input_code, focus=args.focus)
    
    elif args.task == "security":
        if not args.input or not args.input.exists():
            LOG.error("--input required for security task")
            return 1
        
        input_code = args.input.read_text(encoding="utf-8")
        result = assistant.security_analysis(code=input_code, threat_model=args.threat_model)
    
    elif args.task == "architecture":
        if not args.description:
            LOG.error("--description required for architecture task")
            return 1
        
        result = assistant.design_architecture(
            description=args.description,
            scale=args.scale
        )
    
    elif args.task == "explain":
        if not args.input or not args.input.exists():
            LOG.error("--input required for explain task")
            return 1
        
        input_code = args.input.read_text(encoding="utf-8")
        result = assistant.explain_code(code=input_code, detail_level=args.detail)
    
    elif args.task == "analyze":
        if not args.input or not args.input.exists():
            LOG.error("--input required for analyze task")
            return 1
        
        result = assistant.analyze_project(project_path=args.input, focus=args.focus)
    
    elif args.task == "migrate":
        if not args.input or not args.input.exists():
            LOG.error("--input required for migrate task")
            return 1
        if not args.source_lang or not args.target_lang:
            LOG.error("--source-lang and --target-lang required for migrate task")
            return 1
        
        input_code = args.input.read_text(encoding="utf-8")
        result = assistant.migrate_code(
            code=input_code,
            source_language=args.source_lang,
            target_language=args.target_lang
        )
    
    # Save output
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(result, encoding="utf-8")
    LOG.info(f"Saved output to {args.output}")
    
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())