"""Generate flashcards from documents using Ollama with interactive GUI."""

import json
import logging
import tkinter as tk
from tkinter import ttk, messagebox
from pathlib import Path
from typing import Optional, List

from .client_interface import BaseLLMClient
from .rag_system import RAGSystem
from .schemas import FlashcardSet

LOG = logging.getLogger(__name__)


class FlashcardGenerator:
    """Generate flashcards using RAG and Ollama."""
    
    def __init__(
        self,
        llm_client: BaseLLMClient,
        rag_system: RAGSystem
    ):
        self.llm_client = llm_client
        self.rag = rag_system
    
    def generate_flashcards(
        self,
        topic: str,
        card_count: int = 20,
        source_id: Optional[str] = None,
        card_types: Optional[List[str]] = None
    ) -> FlashcardSet:
        """Generate flashcards on a topic."""
        
        if card_types is None:
            card_types = ["basic", "cloze", "definition", "concept"]
        
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
        prompt = f"""Generate {card_count} flashcards on the topic: {topic}

Relevant context from source documents:
{context_text}

Create a mix of these card types: {', '.join(card_types)}
- basic: question on front, answer on back
- cloze: fill-in-the-blank using {{c1::answer}} format
- definition: term on front, definition on back
- concept: concept on front, explanation on back

Make cards:
- Clear and specific
- Focused on key concepts
- Include relevant source references
- Add appropriate tags for categorization
"""
        
        # Define JSON schema
        schema = {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "description": {"type": "string"},
                "cards": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "type": {"type": "string", "enum": card_types},
                            "front": {"type": "string"},
                            "back": {"type": "string"},
                            "tags": {"type": "array", "items": {"type": "string"}},
                            "source_ids": {"type": "array", "items": {"type": "string"}}
                        },
                        "required": ["type", "front", "back"]
                    }
                }
            },
            "required": ["title", "description", "cards"]
        }
        
        try:
            response = self.llm_client.generate_structured(
                prompt=prompt,
                schema=schema,
                temperature=0.7
            )
            
            flashcard_data = json.loads(response)
            return FlashcardSet(**flashcard_data)
            
        except Exception as e:
            LOG.error(f"Failed to generate flashcards: {e}")
            raise
    
    def save_flashcards(self, flashcard_set: FlashcardSet, output_path: Path, format: str = "json"):
        """Save flashcards to file."""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        if format == "json":
            output_path.write_text(
                json.dumps(flashcard_set.model_dump(mode='json'), indent=2, ensure_ascii=False),
                encoding="utf-8"
            )
        elif format == "anki":
            self._save_anki(flashcard_set, output_path)
        else:
            raise ValueError(f"Unsupported format: {format}")
        
        LOG.info(f"Saved flashcards to {output_path}")
    
    def _save_anki(self, flashcard_set: FlashcardSet, output_path: Path):
        """Save flashcards in Anki format (simple text for import)."""
        lines = [
            f"# {flashcard_set.title}",
            f"# {flashcard_set.description}",
            ""
        ]
        
        for card in flashcard_set.cards:
            if card.type == "cloze":
                # Anki cloze format
                lines.append(f"{card.front}\t{card.back}")
            else:
                lines.append(f"{card.front}\t{card.back}")
        
        output_path.write_text("\n".join(lines), encoding="utf-8")


class FlashcardViewer:
    """Interactive GUI for viewing flashcards."""
    
    def __init__(self, flashcard_set: FlashcardSet):
        self.flashcard_set = flashcard_set
        self.current_index = 0
        self.showing_answer = False
        
        self.root = tk.Tk()
        self.root.title(f"Flashcards: {flashcard_set.title}")
        self.root.geometry("600x400")
        
        self._setup_ui()
    
    def _setup_ui(self):
        """Setup the GUI components."""
        # Main container
        main_frame = ttk.Frame(self.root, padding="20")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # Title
        title_label = ttk.Label(
            main_frame,
            text=self.flashcard_set.title,
            font=("Arial", 16, "bold")
        )
        title_label.grid(row=0, column=0, columnspan=2, pady=(0, 10))
        
        # Description
        desc_label = ttk.Label(main_frame, text=self.flashcard_set.description)
        desc_label.grid(row=1, column=0, columnspan=2, pady=(0, 20))
        
        # Card counter
        self.counter_label = ttk.Label(
            main_frame,
            text=f"Card 1/{len(self.flashcard_set.cards)}",
            font=("Arial", 10)
        )
        self.counter_label.grid(row=2, column=0, columnspan=2, pady=(0, 10))
        
        # Card display
        self.card_frame = ttk.Frame(main_frame, borderwidth=2, relief="groove", padding="20")
        self.card_frame.grid(row=3, column=0, columnspan=2, pady=(0, 20), sticky=(tk.W, tk.E))
        
        self.question_label = ttk.Label(
            self.card_frame,
            text="",
            font=("Arial", 14),
            wraplength=500
        )
        self.question_label.grid(row=0, column=0, pady=(0, 10))
        
        self.answer_label = ttk.Label(
            self.card_frame,
            text="",
            font=("Arial", 12),
            wraplength=500,
            foreground="blue"
        )
        self.answer_label.grid(row=1, column=0)
        
        # Tags display
        self.tags_label = ttk.Label(
            main_frame,
            text="",
            font=("Arial", 9),
            foreground="gray"
        )
        self.tags_label.grid(row=4, column=0, columnspan=2, pady=(0, 20))
        
        # Navigation buttons
        button_frame = ttk.Frame(main_frame)
        button_frame.grid(row=5, column=0, columnspan=2)
        
        self.prev_button = ttk.Button(
            button_frame,
            text="Previous",
            command=self.previous_card
        )
        self.prev_button.grid(row=0, column=0, padx=5)
        
        self.flip_button = ttk.Button(
            button_frame,
            text="Show Answer",
            command=self.flip_card
        )
        self.flip_button.grid(row=0, column=1, padx=5)
        
        self.next_button = ttk.Button(
            button_frame,
            text="Next",
            command=self.next_card
        )
        self.next_button.grid(row=0, column=2, padx=5)
        
        # Progress bar
        self.progress = ttk.Progressbar(
            main_frame,
            length=560,
            mode='determinate'
        )
        self.progress.grid(row=6, column=0, columnspan=2, pady=(20, 0))
        
        # Configure grid weights
        main_frame.columnconfigure(0, weight=1)
        main_frame.rowconfigure(3, weight=1)
        
        # Load first card
        self.load_card(0)
        
        # Bind keyboard shortcuts
        self.root.bind('<space>', lambda e: self.flip_card())
        self.root.bind('<Left>', lambda e: self.previous_card())
        self.root.bind('<Right>', lambda e: self.next_card())
    
    def load_card(self, index: int):
        """Load a card by index."""
        if 0 <= index < len(self.flashcard_set.cards):
            self.current_index = index
            card = self.flashcard_set.cards[index]
            
            self.question_label.config(text=card.front)
            self.answer_label.config(text="")
            self.showing_answer = False
            self.flip_button.config(text="Show Answer")
            
            # Update counter
            self.counter_label.config(text=f"Card {index + 1}/{len(self.flashcard_set.cards)}")
            
            # Update tags
            if card.tags:
                self.tags_label.config(text=f"Tags: {', '.join(card.tags)}")
            else:
                self.tags_label.config(text="")
            
            # Update progress
            self.progress['value'] = ((index + 1) / len(self.flashcard_set.cards)) * 100
    
    def flip_card(self):
        """Show/hide the answer."""
        if not self.showing_answer:
            card = self.flashcard_set.cards[self.current_index]
            self.answer_label.config(text=card.back)
            self.flip_button.config(text="Hide Answer")
            self.showing_answer = True
        else:
            self.answer_label.config(text="")
            self.flip_button.config(text="Show Answer")
            self.showing_answer = False
    
    def next_card(self):
        """Go to next card."""
        if self.current_index < len(self.flashcard_set.cards) - 1:
            self.load_card(self.current_index + 1)
    
    def previous_card(self):
        """Go to previous card."""
        if self.current_index > 0:
            self.load_card(self.current_index - 1)
    
    def run(self):
        """Start the GUI main loop."""
        self.root.mainloop()


def main():
    """CLI for flashcard generation."""
    import argparse
    from pathlib import Path
    from .client_interface import create_client
    
    parser = argparse.ArgumentParser(description="Generate flashcards using LLM")
    parser.add_argument("--input", type=Path, required=True, help="Input folder with documents")
    parser.add_argument("--topic", type=str, required=True, help="Flashcard topic")
    parser.add_argument("--output", type=Path, required=True, help="Output file path")
    parser.add_argument("--count", type=int, default=20, help="Number of flashcards to generate")
    parser.add_argument("--format", choices=["json", "anki"], default="json")
    parser.add_argument("--provider", choices=["ollama", "openai", "claude"], default="ollama", help="LLM provider")
    parser.add_argument("--model", type=str, default="qwen2.5", help="Model to use")
    parser.add_argument("--embedding-model", type=str, default=None, help="Embedding model (provider-specific)")
    parser.add_argument("--api-key", type=str, default=None, help="API key for OpenAI/Claude")
    parser.add_argument("--interactive", action="store_true", help="Launch interactive GUI")
    
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
    
    # Generate flashcards
    generator = FlashcardGenerator(llm_client, rag)
    flashcard_set = generator.generate_flashcards(args.topic, args.count)
    
    # Save flashcards
    generator.save_flashcards(flashcard_set, args.output, args.format)
    
    # Launch interactive GUI if requested
    if args.interactive:
        viewer = FlashcardViewer(flashcard_set)
        viewer.run()


if __name__ == "__main__":
    main()