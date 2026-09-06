"""Ollama client implementation."""

import json
import logging
from typing import List, Dict, Any, Optional
import requests

from .client_interface import BaseLLMClient

LOG = logging.getLogger(__name__)


class OllamaClientImpl(BaseLLMClient):
    """Ollama client implementation."""
    
    def __init__(self, model: str, base_url: str = "http://localhost:11434", **kwargs):
        super().__init__(model, **kwargs)
        self.base_url = base_url.rstrip("/")
        self.timeout = kwargs.get("timeout", 120)
    
    def _post(self, endpoint: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Make a POST request to Ollama API."""
        url = f"{self.base_url}{endpoint}"
        try:
            response = requests.post(url, json=data, timeout=self.timeout)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            LOG.error(f"Ollama API request failed: {e}")
            raise RuntimeError(f"Ollama API error: {e}")
    
    def generate(
        self,
        prompt: str,
        system: Optional[str] = None,
        temperature: float = 0.7,
        **kwargs
    ) -> str:
        """Generate text using Ollama."""
        data = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": temperature}
        }
        
        if system:
            data["system"] = system
            
        result = self._post("/api/generate", data)
        return result.get("response", "")
    
    def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        **kwargs
    ) -> str:
        """Chat with Ollama using message history."""
        data = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": temperature}
        }
        
        result = self._post("/api/chat", data)
        return result.get("message", {}).get("content", "")
    
    def embed(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings for text."""
        data = {
            "model": self.model,
            "input": texts
        }
        
        result = self._post("/api/embed", data)
        return result.get("embeddings", [])
    
    def supports_structured_output(self) -> bool:
        """Ollama supports structured output via format parameter."""
        return True
    
    def _generate_structured_native(
        self,
        prompt: str,
        schema: Dict[str, Any],
        system: Optional[str] = None,
        temperature: float = 0.7,
        **kwargs
    ) -> Dict[str, Any]:
        """Native structured output using Ollama's format parameter."""
        data = {
            "model": self.model,
            "prompt": prompt,
            "format": schema,
            "stream": False,
            "options": {"temperature": temperature}
        }
        
        if system:
            data["system"] = system
            
        result = self._post("/api/generate", data)
        response_text = result.get("response", "")
        
        try:
            return json.loads(response_text)
        except json.JSONDecodeError as e:
            LOG.error(f"Failed to parse structured output: {e}")
            raise
    
    def list_models(self) -> List[Dict[str, Any]]:
        """List available models."""
        result = self._post("/api/tags", {})
        return result.get("models", [])
    
    def check_model(self) -> bool:
        """Check if model is available."""
        models = self.list_models()
        model_names = [m.get("name", "").split(":")[0] for m in models]
        return self.model in model_names