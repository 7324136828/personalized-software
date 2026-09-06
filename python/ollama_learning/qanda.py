"""Generate open-ended Q&A prompt sets from documents."""

from __future__ import annotations

import argparse
import json
import logging
import re
from pathlib import Path
from typing import Optional

from .client_interface import BaseLLMClient, create_client
from .rag_system import RAGSystem
from .schemas import QASet


LOG = logging.getLogger(__name__)


class QAGenerator:
    """Generate questions that learners answer in their own words."""

    def __init__(self, llm_client: BaseLLMClient, rag_system: Optional[RAGSystem]):
        self.llm_client = llm_client
        self.rag = rag_system

    def generate(self, topic: str, question_count: int = 8, source_id: Optional[str] = None) -> QASet:
        context_chunks = self.rag.retrieve(topic, top_k=15, source_id=source_id) if self.rag else []
        context_text = "\n\n".join(
            f"[{chunk.filename}]: {chunk.text}" for chunk in context_chunks
        ) or "No specific source context is available."
        prompt = f"""Generate {question_count} thoughtful, open-ended learning questions about: {topic}

Relevant source context:
{context_text}

The learner will type a free-text response. Questions should progress from
comprehension to application and reflection. Do not create multiple-choice
options or include model answers. Give each question a short, stable id using
lowercase letters, numbers, and hyphens. Add a helpful placeholder when useful.
"""
        schema = {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "description": {"type": "string"},
                "questions": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "question": {"type": "string"},
                            "placeholder": {"type": "string"},
                            "required": {"type": "boolean"},
                        },
                        "required": ["id", "question"],
                    },
                },
            },
            "required": ["title", "description", "questions"],
        }
        data = json.loads(self.llm_client.generate_structured(prompt=prompt, schema=schema, temperature=0.7))
        result = QASet(**data)
        if len(result.questions) != question_count:
            LOG.warning("Requested %d questions but received %d", question_count, len(result.questions))
        seen: set[str] = set()
        for index, question in enumerate(result.questions, start=1):
            normalized = re.sub(r"[^a-z0-9-]+", "-", question.id.lower()).strip("-") or f"question-{index}"
            candidate = normalized
            suffix = 2
            while candidate in seen:
                candidate = f"{normalized}-{suffix}"
                suffix += 1
            question.id = candidate
            seen.add(candidate)
        return result

    @staticmethod
    def save(qanda: QASet, output_path: Path) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(qanda.model_dump(mode="json"), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        LOG.info("Saved Q&A set to %s", output_path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate open-ended Q&A prompts using an LLM")
    parser.add_argument("--input", type=Path, required=True, help="Input folder with text documents")
    parser.add_argument("--topic", required=True, help="Q&A topic")
    parser.add_argument("--output", type=Path, required=True, help="Output JSON path")
    parser.add_argument("--count", type=int, default=8, help="Number of prompts")
    parser.add_argument("--provider", choices=["ollama", "openai", "claude"], default="ollama")
    parser.add_argument("--model", default="qwen2.5")
    parser.add_argument("--embedding-model")
    parser.add_argument("--api-key")
    args = parser.parse_args()

    if args.count < 1:
        parser.error("--count must be at least 1")
    logging.basicConfig(level=logging.INFO)
    client_kwargs = {}
    if args.api_key:
        client_kwargs["api_key"] = args.api_key
    if args.embedding_model:
        client_kwargs["embedding_model"] = args.embedding_model
    client = create_client(args.provider, args.model, **client_kwargs)

    rag = None if args.provider == "claude" else RAGSystem(client)
    if rag:
        for file_path in args.input.glob("*.txt"):
            LOG.info("Processing %s", file_path.name)
            rag.add_document_from_file(file_path)
    else:
        LOG.warning("Claude does not provide embeddings; generating without RAG context")

    generator = QAGenerator(client, rag)
    generator.save(generator.generate(args.topic, args.count), args.output)


if __name__ == "__main__":
    main()
