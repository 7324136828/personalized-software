"""Generate mind maps from documents using Ollama."""

import json
import logging
from pathlib import Path
from typing import Optional

from .client_interface import BaseLLMClient
from .rag_system import RAGSystem
from .schemas import MindMap

LOG = logging.getLogger(__name__)


class MindMapGenerator:
    """Generate mind maps using RAG and Ollama."""
    
    def __init__(
        self,
        llm_client: BaseLLMClient,
        rag_system: RAGSystem
    ):
        self.llm_client = llm_client
        self.rag = rag_system
    
    def generate_mindmap(
        self,
        topic: str,
        source_id: Optional[str] = None,
        max_depth: int = 3
    ) -> MindMap:
        """Generate a mind map on a topic."""
        
        # Retrieve relevant context
        LOG.info(f"Retrieving context for topic: {topic}")
        context_chunks = self.rag.retrieve(topic, top_k=15, source_id=source_id)
        
        if not context_chunks:
            LOG.warning("No relevant context found, generating without RAG")
            context_text = "No specific context available."
        else:
            context_text = "\n\n".join([
                f"[{chunk.filename}]: {chunk.text}"
                for chunk in context_chunks
            ])
        
        # Build prompt
        prompt = f"""Generate a hierarchical mind map for: {topic}

Relevant context from source documents:
{context_text}

Create a mind map with:
- A central root node representing the main topic
- 3-6 main branches representing key categories
- Each branch having 2-4 sub-branches with specific details
- Maximum depth of {max_depth} levels
- Clear, concise node names
- Logical organization from general to specific

The mind map should capture the main concepts, relationships, and hierarchies in the topic.
"""
        
        # Define JSON schema for mind map
        schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "children": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "children": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "name": {"type": "string"},
                                        "children": {
                                            "type": "array",
                                            "items": {
                                                "type": "object",
                                                "properties": {
                                                    "name": {"type": "string"}
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            },
            "required": ["name", "children"]
        }
        
        try:
            response = self.llm_client.generate_structured(
                prompt=prompt,
                schema=schema,
                temperature=0.7
            )
            
            mindmap_data = json.loads(response)
            return MindMap(**mindmap_data)
            
        except Exception as e:
            LOG.error(f"Failed to generate mind map: {e}")
            raise
    
    def save_mindmap(self, mindmap: MindMap, output_path: Path, format: str = "markdown"):
        """Save mind map to file."""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        if format == "markdown":
            self._save_markdown(mindmap, output_path)
        elif format == "mermaid":
            self._save_mermaid(mindmap, output_path)
        elif format == "json":
            self._save_json(mindmap, output_path)
        else:
            raise ValueError(f"Unsupported format: {format}")
        
        LOG.info(f"Saved mind map to {output_path}")
    
    def _save_markdown(self, mindmap: MindMap, output_path: Path):
        """Save mind map as Markdown (Markmap format)."""
        lines = [f"# {mindmap.name}"]
        
        def add_node(node, level: int):
            prefix = "#" * (level + 1)
            lines.append(f"{prefix} {node.name}")
            for child in node.children:
                add_node(child, level + 1)
        
        for child in mindmap.children:
            add_node(child, 1)
        
        output_path.write_text("\n".join(lines), encoding="utf-8")
    
    def _save_mermaid(self, mindmap: MindMap, output_path: Path):
        """Save mind map as Mermaid diagram.

        Mermaid's ``mindmap`` dialect derives the hierarchy from indentation
        rather than from explicit edges, and labels containing spaces or
        punctuation must be quoted inside a node shape.
        """
        def escape(name: str) -> str:
            return name.replace('"', "#quot;")

        lines = ["mindmap", f'  root(("{escape(mindmap.name)}"))']
        counter = [0]

        def add_node(node, level: int):
            counter[0] += 1
            indent = "  " * (level + 1)
            lines.append(f'{indent}n{counter[0]}["{escape(node.name)}"]')

            for child in node.children:
                add_node(child, level + 1)

        for child in mindmap.children:
            add_node(child, 1)

        output_path.write_text("\n".join(lines), encoding="utf-8")
    
    def _save_json(self, mindmap: MindMap, output_path: Path):
        """Save mind map as JSON."""
        output_path.write_text(
            json.dumps(mindmap.model_dump(mode='json'), indent=2, ensure_ascii=False),
            encoding="utf-8"
        )


def main():
    """CLI for mind map generation."""
    import argparse
    from pathlib import Path
    from .client_interface import create_client
    
    parser = argparse.ArgumentParser(description="Generate mind maps using LLM")
    parser.add_argument("--input", type=Path, required=True, help="Input folder with documents")
    parser.add_argument("--topic", type=str, required=True, help="Mind map topic")
    parser.add_argument("--output", type=Path, required=True, help="Output file path")
    parser.add_argument("--format", choices=["markdown", "mermaid", "json"], default="markdown")
    parser.add_argument("--provider", choices=["ollama", "openai", "claude"], default="ollama", help="LLM provider")
    parser.add_argument("--model", type=str, default="qwen2.5", help="Model to use")
    parser.add_argument("--embedding-model", type=str, default=None, help="Embedding model (provider-specific)")
    parser.add_argument("--api-key", type=str, default=None, help="API key for OpenAI/Claude")
    parser.add_argument("--max-depth", type=int, default=3, help="Maximum depth of mind map")
    
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
    
    # Generate mind map
    generator = MindMapGenerator(llm_client, rag)
    mindmap = generator.generate_mindmap(args.topic, max_depth=args.max_depth)
    
    # Save mind map
    generator.save_mindmap(mindmap, args.output, args.format)


if __name__ == "__main__":
    main()