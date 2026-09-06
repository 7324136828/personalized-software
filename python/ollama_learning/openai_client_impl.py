"""OpenAI client implementation."""

import json
import logging
from typing import List, Dict, Any, Optional
from openai import OpenAI

from .client_interface import BaseLLMClient

LOG = logging.getLogger(__name__)


class OpenAIClientImpl(BaseLLMClient):
    """OpenAI client implementation."""
    
    def __init__(
        self,
        model: str,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        **kwargs
    ):
        super().__init__(model, **kwargs)
        
        client_kwargs = {}
        if api_key:
            client_kwargs["api_key"] = api_key
        if base_url:
            client_kwargs["base_url"] = base_url
            
        self.client = OpenAI(**client_kwargs)
        self.embedding_model = kwargs.get("embedding_model", "text-embedding-3-small")
    
    def generate(
        self,
        prompt: str,
        system: Optional[str] = None,
        temperature: float = 0.7,
        **kwargs
    ) -> str:
        """Generate text using OpenAI."""
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=temperature,
                **kwargs
            )
            return response.choices[0].message.content
        except Exception as e:
            LOG.error(f"OpenAI API error: {e}")
            raise
    
    def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        **kwargs
    ) -> str:
        """Chat with OpenAI using message history."""
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=temperature,
                **kwargs
            )
            return response.choices[0].message.content
        except Exception as e:
            LOG.error(f"OpenAI API error: {e}")
            raise
    
    def embed(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings using OpenAI."""
        try:
            response = self.client.embeddings.create(
                model=self.embedding_model,
                input=texts
            )
            return [item.embedding for item in response.data]
        except Exception as e:
            LOG.error(f"OpenAI embedding error: {e}")
            raise
    
    def supports_structured_output(self) -> bool:
        """OpenAI supports structured output via response_format."""
        return True
    
    def _generate_structured_native(
        self,
        prompt: str,
        schema: Dict[str, Any],
        system: Optional[str] = None,
        temperature: float = 0.7,
        **kwargs
    ) -> Dict[str, Any]:
        """Native structured output using OpenAI's response_format."""
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                response_format={"type": "json_object"},
                temperature=temperature,
                **kwargs
            )
            content = response.choices[0].message.content
            return json.loads(content)
        except Exception as e:
            LOG.error(f"OpenAI structured output error: {e}")
            raise
    
    def list_models(self) -> List[str]:
        """List available models."""
        try:
            models = self.client.models.list()
            return [model.id for model in models.data]
        except Exception as e:
            LOG.error(f"Failed to list models: {e}")
            return []