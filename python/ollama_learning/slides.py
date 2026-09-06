"""Generate slide decks from documents using Ollama with interactive GUI."""

import json
import logging
import tkinter as tk
from tkinter import ttk, messagebox
from pathlib import Path
from typing import Optional, List

from .client_interface import BaseLLMClient
from .rag_system import RAGSystem
from .schemas import Presentation

LOG = logging.getLogger(__name__)


class SlideGenerator:
    """Generate slide decks using RAG and Ollama."""
    
    def __init__(
        self,
        llm_client: BaseLLMClient,
        rag_system: RAGSystem
    ):
        self.llm_client = llm_client
        self.rag = rag_system
    
    def generate_slides(
        self,
        topic: str,
        slide_count: int = 12,
        source_id: Optional[str] = None,
        style: str = "professional"
    ) -> Presentation:
        """Generate a slide deck on a topic."""
        
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
        prompt = f"""Generate a {slide_count}-slide presentation on: {topic}

Relevant context from source documents:
{context_text}

Presentation style: {style}

For each slide, provide:
- A clear, engaging title
- An optional subtitle
- 3-6 bullet points with key information
- Speaker notes for the presenter
- Optional image query for visual elements
- Source references for citations

Structure the presentation:
1. Title slide
2. Introduction/overview
3. Main content slides (8-10 slides)
4. Summary/conclusions
5. References/Q&A

Make slides:
- Visually balanced (not text-heavy)
- Logically organized
- Action-oriented with clear takeaways
- Supported by source citations
"""
        
        # Define JSON schema
        schema = {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "slides": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string"},
                            "subtitle": {"type": "string"},
                            "bullets": {
                                "type": "array",
                                "items": {"type": "string"}
                            },
                            "speaker_notes": {"type": "string"},
                            "image_query": {"type": "string"},
                            "source_ids": {
                                "type": "array",
                                "items": {"type": "string"}
                            }
                        },
                        "required": ["title"]
                    }
                }
            },
            "required": ["title", "slides"]
        }
        
        try:
            response = self.llm_client.generate_structured(
                prompt=prompt,
                schema=schema,
                temperature=0.7
            )
            
            presentation_data = json.loads(response)
            return Presentation(**presentation_data)
            
        except Exception as e:
            LOG.error(f"Failed to generate slides: {e}")
            raise
    
    def save_slides(self, presentation: Presentation, output_path: Path, format: str = "json"):
        """Save slides to file."""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        if format == "json":
            output_path.write_text(
                json.dumps(presentation.model_dump(mode='json'), indent=2, ensure_ascii=False),
                encoding="utf-8"
            )
        elif format == "markdown":
            self._save_markdown(presentation, output_path)
        else:
            raise ValueError(f"Unsupported format: {format}")
        
        LOG.info(f"Saved slides to {output_path}")
    
    def _save_markdown(self, presentation: Presentation, output_path: Path):
        """Save slides as Markdown (using --- as slide separator)."""
        lines = [f"# {presentation.title}", ""]
        
        for slide in presentation.slides:
            lines.append("---")
            lines.append(f"## {slide.title}")
            
            if slide.subtitle:
                lines.append(f"### {slide.subtitle}")
            
            lines.append("")
            
            for bullet in slide.bullets:
                lines.append(f"- {bullet}")
            
            if slide.speaker_notes:
                lines.append("")
                lines.append(f"**Speaker Notes:** {slide.speaker_notes}")
            
            if slide.source_ids:
                lines.append("")
                lines.append(f"**Sources:** {', '.join(slide.source_ids)}")
            
            lines.append("")
        
        output_path.write_text("\n".join(lines), encoding="utf-8")


class SlideViewer:
    """Interactive GUI for viewing slides."""
    
    def __init__(self, presentation: Presentation):
        self.presentation = presentation
        self.current_index = 0
        
        self.root = tk.Tk()
        self.root.title(f"Presentation: {presentation.title}")
        self.root.geometry("900x600")
        
        self._setup_ui()
    
    def _setup_ui(self):
        """Setup the GUI components."""
        # Main container
        main_frame = ttk.Frame(self.root, padding="20")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # Title
        title_label = ttk.Label(
            main_frame,
            text=self.presentation.title,
            font=("Arial", 18, "bold")
        )
        title_label.grid(row=0, column=0, columnspan=2, pady=(0, 20))
        
        # Slide counter
        self.counter_label = ttk.Label(
            main_frame,
            text=f"Slide 1/{len(self.presentation.slides)}",
            font=("Arial", 12)
        )
        self.counter_label.grid(row=1, column=0, columnspan=2, pady=(0, 10))
        
        # Slide display
        self.slide_frame = ttk.Frame(main_frame, borderwidth=2, relief="groove", padding="30")
        self.slide_frame.grid(row=2, column=0, columnspan=2, pady=(0, 20), sticky=(tk.W, tk.E, tk.N, tk.S))
        
        self.slide_title = ttk.Label(
            self.slide_frame,
            text="",
            font=("Arial", 20, "bold"),
            wraplength=800
        )
        self.slide_title.grid(row=0, column=0, pady=(0, 15))
        
        self.slide_subtitle = ttk.Label(
            self.slide_frame,
            text="",
            font=("Arial", 14, "italic"),
            wraplength=800,
            foreground="gray"
        )
        self.slide_subtitle.grid(row=1, column=0, pady=(0, 20))
        
        # Bullets
        self.bullets_frame = ttk.Frame(self.slide_frame)
        self.bullets_frame.grid(row=2, column=0, sticky=tk.W)
        
        self.bullet_labels = []
        for i in range(8):  # Max 8 bullets
            label = ttk.Label(
                self.bullets_frame,
                text="",
                font=("Arial", 12),
                wraplength=750
            )
            label.grid(row=i, column=0, sticky=tk.W, pady=5)
            self.bullet_labels.append(label)
        
        # Speaker notes (toggleable)
        self.notes_frame = ttk.Frame(main_frame)
        self.notes_frame.grid(row=3, column=0, columnspan=2, pady=(0, 15), sticky=(tk.W, tk.E))
        
        self.notes_label = ttk.Label(
            self.notes_frame,
            text="",
            font=("Arial", 10),
            wraplength=800,
            foreground="blue"
        )
        self.notes_label.grid(row=0, column=0)
        
        # Sources
        self.sources_label = ttk.Label(
            main_frame,
            text="",
            font=("Arial", 9),
            foreground="gray"
        )
        self.sources_label.grid(row=4, column=0, columnspan=2, pady=(0, 15))
        
        # Navigation buttons
        button_frame = ttk.Frame(main_frame)
        button_frame.grid(row=5, column=0, columnspan=2)
        
        self.prev_button = ttk.Button(
            button_frame,
            text="Previous",
            command=self.previous_slide
        )
        self.prev_button.grid(row=0, column=0, padx=5)
        
        self.notes_toggle = ttk.Button(
            button_frame,
            text="Toggle Notes",
            command=self.toggle_notes
        )
        self.notes_toggle.grid(row=0, column=1, padx=5)
        
        self.next_button = ttk.Button(
            button_frame,
            text="Next",
            command=self.next_slide
        )
        self.next_button.grid(row=0, column=2, padx=5)
        
        # Progress bar
        self.progress = ttk.Progressbar(
            main_frame,
            length=860,
            mode='determinate'
        )
        self.progress.grid(row=6, column=0, columnspan=2, pady=(15, 0))
        
        # Configure grid weights
        main_frame.columnconfigure(0, weight=1)
        main_frame.rowconfigure(2, weight=1)
        
        # Load first slide
        self.load_slide(0)
        
        # Bind keyboard shortcuts
        self.root.bind('<Right>', lambda e: self.next_slide())
        self.root.bind('<Left>', lambda e: self.previous_slide())
        self.root.bind('<space>', lambda e: self.toggle_notes())
    
    def load_slide(self, index: int):
        """Load a slide by index."""
        if 0 <= index < len(self.presentation.slides):
            self.current_index = index
            slide = self.presentation.slides[index]
            
            self.slide_title.config(text=slide.title)
            
            if slide.subtitle:
                self.slide_subtitle.config(text=slide.subtitle)
                self.slide_subtitle.grid(row=1, column=0, pady=(0, 20))
            else:
                self.slide_subtitle.config(text="")
                self.slide_subtitle.grid_remove()
            
            # Setup bullets
            for i, label in enumerate(self.bullet_labels):
                if i < len(slide.bullets):
                    label.config(text=f"• {slide.bullets[i]}")
                    label.grid(row=i, column=0, sticky=tk.W, pady=5)
                else:
                    label.config(text="")
                    label.grid_remove()
            
            # Setup notes
            if slide.speaker_notes:
                self.notes_label.config(text=f"Speaker Notes: {slide.speaker_notes}")
            else:
                self.notes_label.config(text="")
            
            # Setup sources
            if slide.source_ids:
                self.sources_label.config(text=f"Sources: {', '.join(slide.source_ids)}")
            else:
                self.sources_label.config(text="")
            
            # Update counter
            self.counter_label.config(text=f"Slide {index + 1}/{len(self.presentation.slides)}")
            
            # Update progress
            self.progress['value'] = ((index + 1) / len(self.presentation.slides)) * 100
    
    def next_slide(self):
        """Go to next slide."""
        if self.current_index < len(self.presentation.slides) - 1:
            self.load_slide(self.current_index + 1)
    
    def previous_slide(self):
        """Go to previous slide."""
        if self.current_index > 0:
            self.load_slide(self.current_index - 1)
    
    def toggle_notes(self):
        """Show/hide speaker notes."""
        if self.notes_frame.winfo_ismapped():
            self.notes_frame.grid_remove()
        else:
            self.notes_frame.grid(row=3, column=0, columnspan=2, pady=(0, 15), sticky=(tk.W, tk.E))
    
    def run(self):
        """Start the GUI main loop."""
        self.root.mainloop()


def main():
    """CLI for slide generation."""
    import argparse
    from pathlib import Path
    from .client_interface import create_client
    
    parser = argparse.ArgumentParser(description="Generate slide decks using LLM")
    parser.add_argument("--input", type=Path, required=True, help="Input folder with documents")
    parser.add_argument("--topic", type=str, required=True, help="Presentation topic")
    parser.add_argument("--output", type=Path, required=True, help="Output file path")
    parser.add_argument("--count", type=int, default=12, help="Number of slides to generate")
    parser.add_argument("--style", type=str, default="professional", help="Presentation style")
    parser.add_argument("--format", choices=["json", "markdown"], default="json")
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
    
    # Generate slides
    generator = SlideGenerator(llm_client, rag)
    presentation = generator.generate_slides(args.topic, args.count, style=args.style)
    
    # Save slides
    generator.save_slides(presentation, args.output, args.format)
    
    # Launch interactive GUI if requested
    if args.interactive:
        viewer = SlideViewer(presentation)
        viewer.run()


if __name__ == "__main__":
    main()