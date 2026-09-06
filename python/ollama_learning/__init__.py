"""Ollama Learning - Generate educational content from documents using multiple LLM providers."""

from .client_interface import BaseLLMClient, create_client
from .ollama_client import OllamaClient
from .ollama_client_impl import OllamaClientImpl
from .openai_client_impl import OpenAIClientImpl
from .claude_client_impl import ClaudeClientImpl
from .rag_system import RAGSystem, DocumentChunk
from .schemas import (
    PodcastOutline, Presentation, MindMap, Report,
    FlashcardSet, Quiz, DataTable
)
from .reports import ReportGenerator
from .flashcards import FlashcardGenerator, FlashcardViewer
from .quiz import QuizGenerator, QuizViewer
from .mindmap import MindMapGenerator
from .slides import SlideGenerator, SlideViewer
from .audio import AudioGenerator
from .datatable import DataTableExtractor

__all__ = [
    "BaseLLMClient",
    "create_client",
    "OllamaClient",
    "OllamaClientImpl",
    "OpenAIClientImpl",
    "ClaudeClientImpl",
    "RAGSystem",
    "DocumentChunk",
    "PodcastOutline",
    "Presentation",
    "MindMap",
    "Report",
    "FlashcardSet",
    "Quiz",
    "DataTable",
    "ReportGenerator",
    "FlashcardGenerator",
    "FlashcardViewer",
    "QuizGenerator",
    "QuizViewer",
    "MindMapGenerator",
    "SlideGenerator",
    "SlideViewer",
    "AudioGenerator",
    "DataTableExtractor",
]