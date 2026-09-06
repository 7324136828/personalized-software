"""Ollama client wrapper for LLM and embedding operations.

This module provides backward compatibility while supporting the new unified client interface.
For new code, use client_interface.create_client() instead.
"""

import json
import logging
from typing import Any, Dict, List, Optional
import requests

LOG = logging.getLogger(__name__)


class OllamaClient:
    """Client for interacting with Ollama API (legacy interface)."""
    
    def __init__(self, base_url: str = "http://localhost:11434"):
        self.base_url = base_url.rstrip("/")
        self.timeout = 120  # seconds
        
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
        model: str,
        prompt: str,
        system: Optional[str] = None,
        format: Optional[Dict[str, Any]] = None,
        temperature: float = 0.7,
        stream: bool = False
    ) -> str:
        """Generate text using Ollama."""
        data = {
            "model": model,
            "prompt": prompt,
            "stream": stream,
            "options": {"temperature": temperature}
        }
        
        if system:
            data["system"] = system
        if format:
            data["format"] = format
            
        result = self._post("/api/generate", data)
        
        if stream:
            # Handle streaming response
            full_response = ""
            for chunk in result:
                if "response" in chunk:
                    full_response += chunk["response"]
            return full_response
        else:
            return result.get("response", "")
    
    def chat(
        self,
        model: str,
        messages: List[Dict[str, str]],
        format: Optional[Dict[str, Any]] = None,
        temperature: float = 0.7
    ) -> str:
        """Chat with Ollama using message history."""
        data = {
            "model": model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": temperature}
        }
        
        if format:
            data["format"] = format
            
        result = self._post("/api/chat", data)
        return result.get("message", {}).get("content", "")
    
    def embed(self, model: str, input: List[str]) -> List[List[float]]:
        """Generate embeddings for text."""
        data = {
            "model": model,
            "input": input
        }
        
        result = self._post("/api/embed", data)
        return result.get("embeddings", [])
    
    def list_models(self) -> List[Dict[str, Any]]:
        """List available models."""
        result = self._post("/api/tags", {})
        return result.get("models", [])
    
    def check_model(self, model: str) -> bool:
        """Check if a model is available."""
        models = self.list_models()
        model_names = [m.get("name", "").split(":")[0] for m in models]
        return model in model_names