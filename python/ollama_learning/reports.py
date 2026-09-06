"""Generate structured reports from documents using Ollama."""

import json
import logging
from pathlib import Path
from typing import Optional, List

from .client_interface import BaseLLMClient
from .rag_system import RAGSystem
from .schemas import Report

LOG = logging.getLogger(__name__)


def _format_citation(citation) -> str:
    """Render a citation, omitting page and chunk parts that are not set."""
    parts = [citation.source_id]
    if citation.page is not None:
        parts.append(f"p.{citation.page}")
    if citation.chunk_id:
        parts.append(citation.chunk_id)
    return ":".join(parts)


class ReportGenerator:
    """Generate reports using RAG and Ollama."""
    
    def __init__(
        self,
        llm_client: BaseLLMClient,
        rag_system: RAGSystem
    ):
        self.llm_client = llm_client
        self.rag = rag_system
    
    def generate_report(
        self,
        topic: str,
        source_id: Optional[str] = None,
        sections: Optional[List[str]] = None
    ) -> Report:
        """Generate a structured report on a topic."""
        
        # Default sections if not provided
        if sections is None:
            sections = [
                "Introduction",
                "Background",
                "Key Findings",
                "Analysis",
                "Conclusions"
            ]
        
        # Retrieve relevant context
        LOG.info(f"Retrieving context for topic: {topic}")
        context_chunks = self.rag.retrieve(topic, top_k=10, source_id=source_id)
        
        if not context_chunks:
            LOG.warning("No relevant context found, generating without RAG")
            context_text = "No specific context available."
        else:
            context_text = "\n\n".join([
                f"[{chunk.filename}, page {chunk.page or 'N/A'}]: {chunk.text}"
                for chunk in context_chunks
            ])
        
        # Build prompt for structured output
        prompt = f"""Generate a comprehensive report on: {topic}

Relevant context from source documents:
{context_text}

Include the following sections: {', '.join(sections)}

For each section, provide:
1. Clear, well-structured content
2. Key claims with specific citations to the source documents
3. Evidence-based analysis

Citations should reference source documents using the format: [source_id:page]
"""
        
        # Define JSON schema for structured output
        schema = {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "executive_summary": {"type": "string"},
                "sections": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string"},
                            "content": {"type": "string"},
                            "claims": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "claim": {"type": "string"},
                                        "citations": {
                                            "type": "array",
                                            "items": {
                                                "type": "object",
                                                "properties": {
                                                    "source_id": {"type": "string"},
                                                    "page": {"type": "integer"},
                                                    "chunk_id": {"type": "string"}
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                },
                "conclusions": {"type": "string"}
            },
            "required": ["title", "executive_summary", "sections", "conclusions"]
        }
        
        try:
            response = self.llm_client.generate_structured(
                prompt=prompt,
                schema=schema,
                temperature=0.7
            )
            
            # Parse JSON response
            report_data = json.loads(response)
            return Report(**report_data)
            
        except Exception as e:
            LOG.error(f"Failed to generate report: {e}")
            raise
    
    def save_report(self, report: Report, output_path: Path, format: str = "markdown"):
        """Save report to file in specified format."""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        if format == "markdown":
            self._save_markdown(report, output_path)
        elif format == "json":
            self._save_json(report, output_path)
        elif format == "html":
            self._save_html(report, output_path)
        else:
            raise ValueError(f"Unsupported format: {format}")
    
    def _save_markdown(self, report: Report, output_path: Path):
        """Save report as Markdown."""
        lines = [
            f"# {report.title}",
            "",
            "## Executive Summary",
            report.executive_summary,
            ""
        ]
        
        for section in report.sections:
            lines.append(f"## {section.title}")
            lines.append(section.content)
            
            if section.claims:
                lines.append("")
                lines.append("### Key Claims")
                for claim in section.claims:
                    lines.append(f"- {claim.claim}")
                    if claim.citations:
                        citations = ", ".join([f"[{_format_citation(c)}]" for c in claim.citations])
                        lines.append(f"  Sources: {citations}")
                lines.append("")
        
        lines.append("## Conclusions")
        lines.append(report.conclusions)
        
        output_path.write_text("\n".join(lines), encoding="utf-8")
        LOG.info(f"Saved report to {output_path}")
    
    def _save_json(self, report: Report, output_path: Path):
        """Save report as JSON."""
        output_path.write_text(
            json.dumps(report.model_dump(mode='json'), indent=2, ensure_ascii=False),
            encoding="utf-8"
        )
        LOG.info(f"Saved report to {output_path}")
    
    def _save_html(self, report: Report, output_path: Path):
        """Save report as HTML."""
        html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>{report.title}</title>
    <style>
        body {{ font-family: Arial, sans-serif; max-width: 800px; margin: 0 auto; padding: 20px; }}
        h1 {{ color: #333; }}
        h2 {{ color: #666; border-bottom: 2px solid #eee; padding-bottom: 10px; }}
        .claim {{ background: #f9f9f9; padding: 10px; margin: 10px 0; border-left: 3px solid #007bff; }}
        .citation {{ color: #666; font-size: 0.9em; }}
    </style>
</head>
<body>
    <h1>{report.title}</h1>
    
    <h2>Executive Summary</h2>
    <p>{report.executive_summary}</p>
"""
        
        for section in report.sections:
            html += f"""
    <h2>{section.title}</h2>
    <p>{section.content}</p>
"""
            if section.claims:
                html += "    <h3>Key Claims</h3>\n"
                for claim in section.claims:
                    citations = ", ".join([_format_citation(c) for c in claim.citations])
                    html += f"""
    <div class="claim">
        <p>{claim.claim}</p>
        <p class="citation">Sources: {citations}</p>
    </div>
"""
        
        html += f"""
    <h2>Conclusions</h2>
    <p>{report.conclusions}</p>
</body>
</html>
"""
        output_path.write_text(html, encoding="utf-8")
        LOG.info(f"Saved report to {output_path}")


def main():
    """CLI for report generation."""
    import argparse
    from pathlib import Path
    from .client_interface import create_client
    
    parser = argparse.ArgumentParser(description="Generate reports using LLM")
    parser.add_argument("--input", type=Path, required=True, help="Input folder with documents")
    parser.add_argument("--topic", type=str, required=True, help="Report topic")
    parser.add_argument("--output", type=Path, required=True, help="Output file path")
    parser.add_argument("--format", choices=["markdown", "json", "html"], default="markdown")
    parser.add_argument("--provider", choices=["ollama", "openai", "claude"], default="ollama", help="LLM provider")
    parser.add_argument("--model", type=str, default="qwen2.5", help="Model to use")
    parser.add_argument("--embedding-model", type=str, default=None, help="Embedding model (provider-specific)")
    parser.add_argument("--api-key", type=str, default=None, help="API key for OpenAI/Claude")
    
    args = parser.parse_args()
    
    logging.basicConfig(level=logging.INFO)
    
    # Initialize client
    client_kwargs = {}
    if args.api_key:
        client_kwargs["api_key"] = args.api_key
    if args.embedding_model:
        client_kwargs["embedding_model"] = args.embedding_model
    
    llm_client = create_client(args.provider, args.model, **client_kwargs)
    
    # Initialize RAG (skip for Claude since it doesn't have embeddings)
    if args.provider == "claude":
        LOG.warning("Claude doesn't support embeddings. RAG will be disabled.")
        rag = None
    else:
        rag = RAGSystem(llm_client)
    
    # Ingest documents (only if RAG is available)
    if rag:
        LOG.info(f"Ingesting documents from {args.input}")
        for file_path in args.input.glob("*.txt"):
            LOG.info(f"Processing {file_path.name}")
            rag.add_document_from_file(file_path)
    else:
        LOG.info("Skipping document ingestion (no RAG available)")
    
    # Generate report
    generator = ReportGenerator(llm_client, rag)
    report = generator.generate_report(args.topic)
    
    # Save report
    generator.save_report(report, args.output, args.format)


if __name__ == "__main__":
    main()