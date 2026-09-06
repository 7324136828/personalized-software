"""Unified client interface for multiple LLM providers."""

from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
import logging

LOG = logging.getLogger(__name__)


class BaseLLMClient(ABC):
    """Abstract base class for LLM clients."""
    
    def __init__(self, model: str, **kwargs):
        self.model = model
        self.kwargs = kwargs
    
    @abstractmethod
    def generate(
        self,
        prompt: str,
        system: Optional[str] = None,
        temperature: float = 0.7,
        **kwargs
    ) -> str:
        """Generate text from a prompt."""
        pass
    
    @abstractmethod
    def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        **kwargs
    ) -> str:
        """Chat with message history."""
        pass
    
    @abstractmethod
    def embed(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings for texts."""
        pass
    
    @abstractmethod
    def supports_structured_output(self) -> bool:
        """Check if client supports structured output."""
        pass
    
    def generate_structured(
        self,
        prompt: str,
        schema: Dict[str, Any],
        system: Optional[str] = None,
        temperature: float = 0.7,
        **kwargs
    ) -> Dict[str, Any]:
        """Generate structured output using JSON schema."""
        if not self.supports_structured_output():
            # Fallback: generate text and parse JSON
            prompt_with_schema = f"""
{prompt}

Respond ONLY with valid JSON matching this schema:
{schema}

Do not include any other text or explanations.
"""
            response = self.generate(prompt_with_schema, system, temperature, **kwargs)
            import json
            try:
                return json.loads(response)
            except json.JSONDecodeError as e:
                LOG.error(f"Failed to parse JSON response: {e}")
                raise
        else:
            return self._generate_structured_native(prompt, schema, system, temperature, **kwargs)
    
    def _generate_structured_native(
        self,
        prompt: str,
        schema: Dict[str, Any],
        system: Optional[str] = None,
        temperature: float = 0.7,
        **kwargs
    ) -> Dict[str, Any]:
        """Native structured output implementation (override in subclasses)."""
        raise NotImplementedError("Native structured output not implemented for this client")


def create_client(provider: str, model: str, **kwargs) -> BaseLLMClient:
    """Factory function to create appropriate client."""
    provider = provider.lower()
    
    if provider == "ollama":
        from .ollama_client_impl import OllamaClientImpl
        return OllamaClientImpl(model, **kwargs)
    elif provider == "openai":
        from .openai_client_impl import OpenAIClientImpl
        return OpenAIClientImpl(model, **kwargs)
    elif provider == "claude":
        from .claude_client_impl import ClaudeClientImpl
        return ClaudeClientImpl(model, **kwargs)
    else:
        raise ValueError(f"Unknown provider: {provider}. Use 'ollama', 'openai', or 'claude'")