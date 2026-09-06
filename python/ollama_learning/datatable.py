"""Extract structured data tables from documents using Ollama."""

import json
import logging
import pandas as pd
from pathlib import Path
from typing import Optional, List, Dict

from .client_interface import BaseLLMClient
from .rag_system import RAGSystem
from .schemas import DataTable, StudyField

LOG = logging.getLogger(__name__)


class DataTableExtractor:
    """Extract structured data using RAG and Ollama."""
    
    def __init__(
        self,
        llm_client: BaseLLMClient,
        rag_system: RAGSystem
    ):
        self.llm_client = llm_client
        self.rag = rag_system
    
    def define_fields(
        self,
        field_descriptions: List[Dict[str, str]]
    ) -> List[StudyField]:
        """Convert field descriptions to StudyField objects."""
        return [
            StudyField(
                name=field["name"],
                description=field["description"],
                example=field.get("example")
            )
            for field in field_descriptions
        ]
    
    def extract_data(
        self,
        topic: str,
        fields: List[StudyField],
        source_id: Optional[str] = None
    ) -> DataTable:
        """Extract structured data on a topic."""
        
        # Retrieve relevant context
        LOG.info(f"Retrieving context for topic: {topic}")
        context_chunks = self.rag.retrieve(topic, top_k=20, source_id=source_id)
        
        if not context_chunks:
            LOG.warning("No relevant context found, extracting without RAG")
            context_text = "No specific context available."
        else:
            context_text = "\n\n".join([
                f"[{chunk.filename}, page {chunk.page or 'N/A'}]: {chunk.text}"
                for chunk in context_chunks
            ])
        
        # Build field descriptions for prompt
        field_descriptions = "\n".join([
            f"- {field.name}: {field.description}"
            + (f" (example: {field.example})" if field.example else "")
            for field in fields
        ])
        
        # Build prompt
        prompt = f"""Extract structured data from the following documents about: {topic}

Fields to extract:
{field_descriptions}

Relevant context from source documents:
{context_text}

For each relevant entity/study/entry found:
1. Extract values for all specified fields
2. Use "N/A" if a field is not mentioned
3. Include the source document ID and page number
4. Be precise and accurate - only extract what is explicitly stated
5. Return as many rows as relevant entities are found

The data should be accurate, well-structured, and properly sourced.
"""
        
        # Define JSON schema
        field_names = [field.name for field in fields]
        schema = {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "fields": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "description": {"type": "string"},
                            "example": {"type": "string"}
                        },
                        "required": ["name", "description"]
                    }
                },
                "data": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            **{name: {"type": "string"} for name in field_names},
                            "source_id": {"type": "string"},
                            "page": {"type": "integer"}
                        },
                        "required": field_names + ["source_id"]
                    }
                }
            },
            "required": ["title", "fields", "data"]
        }
        
        try:
            response = self.llm_client.generate_structured(
                prompt=prompt,
                schema=schema,
                temperature=0.3  # Lower temperature for extraction
            )
            
            table_data = json.loads(response)
            return DataTable(**table_data)
            
        except Exception as e:
            LOG.error(f"Failed to extract data: {e}")
            raise
    
    def save_table(
        self,
        table: DataTable,
        output_path: Path,
        format: str = "csv"
    ):
        """Save data table to file."""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        if format == "json":
            output_path.write_text(
                json.dumps(table.model_dump(mode='json'), indent=2, ensure_ascii=False),
                encoding="utf-8"
            )
        elif format == "csv":
            self._save_csv(table, output_path)
        elif format == "excel":
            self._save_excel(table, output_path)
        else:
            raise ValueError(f"Unsupported format: {format}")
        
        LOG.info(f"Saved data table to {output_path}")
    
    def _save_csv(self, table: DataTable, output_path: Path):
        """Save table as CSV."""
        df = pd.DataFrame(table.data)
        df.to_csv(output_path, index=False, encoding="utf-8")
    
    def _save_excel(self, table: DataTable, output_path: Path):
        """Save table as Excel."""
        df = pd.DataFrame(table.data)
        df.to_excel(output_path, index=False, engine='openpyxl')
    
    def to_dataframe(self, table: DataTable) -> pd.DataFrame:
        """Convert DataTable to pandas DataFrame."""
        return pd.DataFrame(table.data)


def main():
    """CLI for data table extraction."""
    import argparse
    from pathlib import Path
    from .client_interface import create_client
    
    parser = argparse.ArgumentParser(description="Extract data tables using LLM")
    parser.add_argument("--input", type=Path, required=True, help="Input folder with documents")
    parser.add_argument("--topic", type=str, required=True, help="Extraction topic")
    parser.add_argument("--output", type=Path, required=True, help="Output file path")
    parser.add_argument("--fields", type=str, required=True, 
                       help="JSON file with field definitions or inline JSON string")
    parser.add_argument("--format", choices=["json", "csv", "excel"], default="csv")
    parser.add_argument("--provider", choices=["ollama", "openai", "claude"], default="ollama", help="LLM provider")
    parser.add_argument("--model", type=str, default="qwen2.5", help="Model to use")
    parser.add_argument("--embedding-model", type=str, default=None, help="Embedding model (provider-specific)")
    parser.add_argument("--api-key", type=str, default=None, help="API key for OpenAI/Claude")
    
    args = parser.parse_args()
    
    logging.basicConfig(level=logging.INFO)
    
    # Load field definitions
    fields_path = Path(args.fields)
    if fields_path.exists():
        field_descriptions = json.loads(fields_path.read_text(encoding="utf-8"))
    else:
        # Try parsing as inline JSON
        try:
            field_descriptions = json.loads(args.fields)
        except json.JSONDecodeError:
            LOG.error("Fields must be a valid JSON file path or JSON string")
            return 1
    
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
    
    # Define fields
    extractor = DataTableExtractor(llm_client, rag)
    fields = extractor.define_fields(field_descriptions)
    
    # Extract data
    table = extractor.extract_data(args.topic, fields)
    
    # Save table
    extractor.save_table(table, args.output, args.format)


if __name__ == "__main__":
    main()