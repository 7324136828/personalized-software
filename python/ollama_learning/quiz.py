"""Generate quizzes from documents using Ollama with interactive GUI."""

import json
import logging
import tkinter as tk
from tkinter import ttk, messagebox
from pathlib import Path
from typing import Optional, List

from .client_interface import BaseLLMClient
from .rag_system import RAGSystem
from .schemas import Quiz

LOG = logging.getLogger(__name__)


class QuizGenerator:
    """Generate quizzes using RAG and Ollama."""
    
    def __init__(
        self,
        llm_client: BaseLLMClient,
        rag_system: RAGSystem
    ):
        self.llm_client = llm_client
        self.rag = rag_system
    
    def generate_quiz(
        self,
        topic: str,
        question_count: int = 10,
        source_id: Optional[str] = None,
        difficulty: str = "understanding"
    ) -> Quiz:
        """Generate a quiz on a topic."""
        
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
        prompt = f"""Generate {question_count} multiple-choice quiz questions on: {topic}

Relevant context from source documents:
{context_text}

Difficulty level: {difficulty}

For each question:
- Provide 4-6 answer options
- Only one correct answer
- Include clear explanation
- Reference source documents where applicable
- Ensure distractors are plausible but clearly incorrect

Question types based on Bloom's taxonomy:
- recall: basic factual recall
- understanding: comprehension and explanation
- application: applying concepts to new situations
- analysis: breaking down complex ideas
- expert: synthesis and evaluation
"""
        
        # Define JSON schema
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
                            "question": {"type": "string"},
                            "options": {
                                "type": "array",
                                "items": {"type": "string"},
                                "minItems": 4,
                                "maxItems": 6
                            },
                            "correct": {"type": "integer"},
                            "explanation": {"type": "string"},
                            "difficulty": {
                                "type": "string",
                                "enum": ["recall", "understanding", "application", "analysis", "expert"]
                            },
                            "sources": {"type": "array", "items": {"type": "string"}}
                        },
                        "required": ["question", "options", "correct", "explanation"]
                    }
                }
            },
            "required": ["title", "description", "questions"]
        }
        
        try:
            response = self.llm_client.generate_structured(
                prompt=prompt,
                schema=schema,
                temperature=0.7
            )
            
            quiz_data = json.loads(response)
            return Quiz(**quiz_data)
            
        except Exception as e:
            LOG.error(f"Failed to generate quiz: {e}")
            raise
    
    def save_quiz(self, quiz: Quiz, output_path: Path, format: str = "json"):
        """Save quiz to file."""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        if format == "json":
            output_path.write_text(
                json.dumps(quiz.model_dump(mode='json'), indent=2, ensure_ascii=False),
                encoding="utf-8"
            )
        else:
            raise ValueError(f"Unsupported format: {format}")
        
        LOG.info(f"Saved quiz to {output_path}")


class QuizViewer:
    """Interactive GUI for taking quizzes."""
    
    def __init__(self, quiz: Quiz):
        self.quiz = quiz
        self.current_index = 0
        self.user_answers = [None] * len(quiz.questions)
        self.score = 0
        
        self.root = tk.Tk()
        self.root.title(f"Quiz: {quiz.title}")
        self.root.geometry("700x500")
        
        self._setup_ui()
    
    def _setup_ui(self):
        """Setup the GUI components."""
        # Main container
        main_frame = ttk.Frame(self.root, padding="20")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # Title
        title_label = ttk.Label(
            main_frame,
            text=self.quiz.title,
            font=("Arial", 16, "bold")
        )
        title_label.grid(row=0, column=0, columnspan=2, pady=(0, 5))
        
        # Description
        desc_label = ttk.Label(main_frame, text=self.quiz.description)
        desc_label.grid(row=1, column=0, columnspan=2, pady=(0, 15))
        
        # Question counter
        self.counter_label = ttk.Label(
            main_frame,
            text=f"Question 1/{len(self.quiz.questions)}",
            font=("Arial", 11)
        )
        self.counter_label.grid(row=2, column=0, columnspan=2, pady=(0, 10))
        
        # Question display
        self.question_frame = ttk.Frame(main_frame, borderwidth=2, relief="groove", padding="20")
        self.question_frame.grid(row=3, column=0, columnspan=2, pady=(0, 15), sticky=(tk.W, tk.E))
        
        self.question_label = ttk.Label(
            self.question_frame,
            text="",
            font=("Arial", 13),
            wraplength=600
        )
        self.question_label.grid(row=0, column=0, pady=(0, 15))
        
        # Options
        self.option_var = tk.StringVar()
        self.option_buttons = []
        for i in range(6):  # Max 6 options
            btn = ttk.Radiobutton(
                self.question_frame,
                text="",
                variable=self.option_var,
                value=str(i),
                command=self.on_answer_select
            )
            btn.grid(row=i+1, column=0, sticky=tk.W, pady=2)
            self.option_buttons.append(btn)
        
        # Explanation (hidden initially)
        self.explanation_frame = ttk.Frame(main_frame)
        self.explanation_frame.grid(row=4, column=0, columnspan=2, pady=(0, 15), sticky=(tk.W, tk.E))
        
        self.explanation_label = ttk.Label(
            self.explanation_frame,
            text="",
            font=("Arial", 11),
            wraplength=600,
            foreground="green"
        )
        self.explanation_label.grid(row=0, column=0)
        
        # Navigation buttons
        button_frame = ttk.Frame(main_frame)
        button_frame.grid(row=5, column=0, columnspan=2)
        
        self.prev_button = ttk.Button(
            button_frame,
            text="Previous",
            command=self.previous_question
        )
        self.prev_button.grid(row=0, column=0, padx=5)
        
        self.submit_button = ttk.Button(
            button_frame,
            text="Submit Answer",
            command=self.submit_answer
        )
        self.submit_button.grid(row=0, column=1, padx=5)
        
        self.next_button = ttk.Button(
            button_frame,
            text="Next",
            command=self.next_question
        )
        self.next_button.grid(row=0, column=2, padx=5)
        
        # Progress bar
        self.progress = ttk.Progressbar(
            main_frame,
            length=660,
            mode='determinate'
        )
        self.progress.grid(row=6, column=0, columnspan=2, pady=(15, 0))
        
        # Score display
        self.score_label = ttk.Label(
            main_frame,
            text="Score: 0/0",
            font=("Arial", 11, "bold")
        )
        self.score_label.grid(row=7, column=0, columnspan=2, pady=(10, 0))
        
        # Configure grid weights
        main_frame.columnconfigure(0, weight=1)
        main_frame.rowconfigure(3, weight=1)
        
        # Load first question
        self.load_question(0)
    
    def load_question(self, index: int):
        """Load a question by index."""
        if 0 <= index < len(self.quiz.questions):
            self.current_index = index
            question = self.quiz.questions[index]
            
            self.question_label.config(text=question.question)
            
            # Setup options
            for i, btn in enumerate(self.option_buttons):
                if i < len(question.options):
                    btn.config(text=question.options[i], state=tk.NORMAL)
                else:
                    btn.config(text="", state=tk.HIDDEN)
            
            # Reset selection
            self.option_var.set("")
            
            # Hide explanation
            self.explanation_label.config(text="")
            
            # Update counter
            self.counter_label.config(text=f"Question {index + 1}/{len(self.quiz.questions)}")
            
            # Update progress
            self.progress['value'] = ((index + 1) / len(self.quiz.questions)) * 100
            
            # Enable/disable buttons
            self.submit_button.config(state=tk.NORMAL)
            if self.user_answers[index] is not None:
                # Already answered
                self.explanation_label.config(text=question.explanation)
                self.submit_button.config(state=tk.DISABLED)
    
    def on_answer_select(self):
        """Handle option selection."""
        pass  # Just update the variable
    
    def submit_answer(self):
        """Submit the current answer."""
        if not self.option_var.get():
            messagebox.showwarning("No Answer", "Please select an answer")
            return
        
        question = self.quiz.questions[self.current_index]
        user_answer = int(self.option_var.get())
        
        self.user_answers[self.current_index] = user_answer
        
        # Show explanation
        if user_answer == question.correct:
            self.explanation_label.config(
                text=f"✓ Correct! {question.explanation}",
                foreground="green"
            )
            self.score += 1
        else:
            correct_text = question.options[question.correct]
            self.explanation_label.config(
                text=f"✗ Incorrect. Correct answer: {correct_text}\n\n{question.explanation}",
                foreground="red"
            )
        
        # Update score display
        answered = sum(1 for a in self.user_answers if a is not None)
        self.score_label.config(text=f"Score: {self.score}/{answered}")
        
        # Disable submit button
        self.submit_button.config(state=tk.DISABLED)
    
    def next_question(self):
        """Go to next question."""
        if self.current_index < len(self.quiz.questions) - 1:
            self.load_question(self.current_index + 1)
        else:
            self.show_final_results()
    
    def previous_question(self):
        """Go to previous question."""
        if self.current_index > 0:
            self.load_question(self.current_index - 1)
    
    def show_final_results(self):
        """Show final quiz results."""
        total = len(self.quiz.questions)
        percentage = (self.score / total) * 100 if total > 0 else 0
        
        result_text = f"Quiz Complete!\n\nScore: {self.score}/{total} ({percentage:.1f}%)\n\n"
        
        if percentage >= 90:
            result_text += "Excellent! You mastered this topic."
        elif percentage >= 70:
            result_text += "Good job! You have a solid understanding."
        elif percentage >= 50:
            result_text += "Not bad, but there's room for improvement."
        else:
            result_text += "Keep studying! Review the material and try again."
        
        messagebox.showinfo("Quiz Results", result_text)
        self.root.quit()
    
    def run(self):
        """Start the GUI main loop."""
        self.root.mainloop()


def main():
    """CLI for quiz generation."""
    import argparse
    from pathlib import Path
    from .client_interface import create_client
    
    parser = argparse.ArgumentParser(description="Generate quizzes using LLM")
    parser.add_argument("--input", type=Path, required=True, help="Input folder with documents")
    parser.add_argument("--topic", type=str, required=True, help="Quiz topic")
    parser.add_argument("--output", type=Path, required=True, help="Output file path")
    parser.add_argument("--count", type=int, default=10, help="Number of questions to generate")
    parser.add_argument("--difficulty", choices=["recall", "understanding", "application", "analysis", "expert"], 
                       default="understanding", help="Question difficulty")
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
    
    # Generate quiz
    generator = QuizGenerator(llm_client, rag)
    quiz = generator.generate_quiz(args.topic, args.count, difficulty=args.difficulty)
    
    # Save quiz
    generator.save_quiz(quiz, args.output)
    
    # Launch interactive GUI if requested
    if args.interactive:
        viewer = QuizViewer(quiz)
        viewer.run()


if __name__ == "__main__":
    main()