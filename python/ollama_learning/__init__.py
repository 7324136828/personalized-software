"""Ollama Learning - Generate educational content from documents using multiple LLM providers."""

from importlib import import_module

from .client_interface import BaseLLMClient, create_client
from .schemas import (
    PodcastOutline, Presentation, MindMap, Report,
    FlashcardSet, Quiz, QASet, QAPrompt, DataTable
)


_LAZY_EXPORTS = {
    'OllamaClient': '.ollama_client',
    'OllamaClientImpl': '.ollama_client_impl',
    'OpenAIClientImpl': '.openai_client_impl',
    'ClaudeClientImpl': '.claude_client_impl',
    'RAGSystem': '.rag_system',
    'DocumentChunk': '.rag_system',
    'ReportGenerator': '.reports',
    'FlashcardGenerator': '.flashcards',
    'FlashcardViewer': '.flashcards',
    'QuizGenerator': '.quiz',
    'QuizViewer': '.quiz',
    'QAGenerator': '.qanda',
    'MindMapGenerator': '.mindmap',
    'SlideGenerator': '.slides',
    'SlideViewer': '.slides',
    'AudioGenerator': '.audio',
    'DataTableExtractor': '.datatable',
}


def __getattr__(name: str):
    module_name = _LAZY_EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f'module {__name__!r} has no attribute {name!r}')
    value = getattr(import_module(module_name, __name__), name)
    globals()[name] = value
    return value

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
    "QASet",
    "QAPrompt",
    "DataTable",
    "ReportGenerator",
    "FlashcardGenerator",
    "FlashcardViewer",
    "QuizGenerator",
    "QuizViewer",
    "QAGenerator",
    "MindMapGenerator",
    "SlideGenerator",
    "SlideViewer",
    "AudioGenerator",
    "DataTableExtractor",
]
