"""Claude client implementation."""

import json
import logging
from typing import List, Dict, Any, Optional
from anthropic import Anthropic

from .client_interface import BaseLLMClient

LOG = logging.getLogger(__name__)


class ClaudeClientImpl(BaseLLMClient):
    """Claude client implementation."""
    
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
            
        self.client = Anthropic(**client_kwargs)
        self.embedding_model = kwargs.get("embedding_model", None)  # Claude doesn't have embeddings
        
        # Check if this is Claude Code (claude-3-5-sonnet for coding)
        self.is_claude_code = "claude-3-5-sonnet" in model.lower() or "claude-code" in model.lower()
    
    def generate(
        self,
        prompt: str,
        system: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        **kwargs
    ) -> str:
        """Generate text using Claude."""
        try:
            if system:
                response = self.client.messages.create(
                    model=self.model,
                    max_tokens=max_tokens,
                    system=system,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=temperature,
                    **kwargs
                )
            else:
                response = self.client.messages.create(
                    model=self.model,
                    max_tokens=max_tokens,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=temperature,
                    **kwargs
                )
            return response.content[0].text
        except Exception as e:
            LOG.error(f"Claude API error: {e}")
            raise
    
    def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 4096,
        **kwargs
    ) -> str:
        """Chat with Claude using message history."""
        try:
            # Convert messages to Claude format
            claude_messages = []
            for msg in messages:
                claude_messages.append({
                    "role": msg["role"],
                    "content": msg["content"]
                })
            
            response = self.client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                messages=claude_messages,
                temperature=temperature,
                **kwargs
            )
            return response.content[0].text
        except Exception as e:
            LOG.error(f"Claude API error: {e}")
            raise
    
    def embed(self, texts: List[str]) -> List[List[float]]:
        """Claude doesn't provide embeddings API."""
        raise NotImplementedError(
            "Claude doesn't provide an embeddings API. "
            "Use a different provider for embeddings or implement a custom solution."
        )
    
    def supports_structured_output(self) -> bool:
        """Claude supports structured output via tools (not native JSON schema)."""
        return False  # Claude doesn't have native JSON schema like OpenAI
    
    def generate_with_tools(
        self,
        prompt: str,
        tools: List[Dict[str, Any]],
        system: Optional[str] = None,
        temperature: float = 0.7,
        **kwargs
    ) -> Any:
        """Generate text with tool calling support (for Claude Code)."""
        try:
            if system:
                response = self.client.messages.create(
                    model=self.model,
                    max_tokens=4096,
                    system=system,
                    messages=[{"role": "user", "content": prompt}],
                    tools=tools,
                    temperature=temperature,
                    **kwargs
                )
            else:
                response = self.client.messages.create(
                    model=self.model,
                    max_tokens=4096,
                    messages=[{"role": "user", "content": prompt}],
                    tools=tools,
                    temperature=temperature,
                    **kwargs
                )
            return response
        except Exception as e:
            LOG.error(f"Claude tool calling error: {e}")
            raise
    
    def list_models(self) -> List[str]:
        """Return known Claude models."""
        return [
            "claude-3-5-sonnet-20241022",
            "claude-3-5-haiku-20241022",
            "claude-3-opus-20240229",
            "claude-3-sonnet-20240229",
            "claude-3-haiku-20240307"
        ]