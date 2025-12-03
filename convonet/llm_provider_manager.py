"""
LLM Provider Manager - Supports multiple LLM providers (Claude, Gemini, OpenAI)
"""

import os
from typing import Optional, Literal
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage

# Provider type
LLMProvider = Literal["claude", "gemini", "openai"]


class LLMProviderManager:
    """Manages multiple LLM providers and provides a unified interface."""
    
    def __init__(self):
        self.providers = {}
        self._initialize_providers()
    
    def _initialize_providers(self):
        """Initialize available LLM providers."""
        # Claude (Anthropic)
        try:
            from langchain_anthropic import ChatAnthropic
            self.providers["claude"] = {
                "class": ChatAnthropic,
                "name": "Claude (Anthropic)",
                "api_key_env": "ANTHROPIC_API_KEY",
                "model_env": "ANTHROPIC_MODEL",
                "default_model": "claude-sonnet-4-20250514",
                "available": bool(os.getenv("ANTHROPIC_API_KEY")),
            }
        except ImportError:
            self.providers["claude"] = {"available": False, "name": "Claude (Anthropic)"}
        
        # Gemini (Google)
        try:
            # Try both possible import paths
            try:
                from langchain_google_genai import ChatGoogleGenerativeAI
            except ImportError:
                from langchain_google_vertexai import ChatVertexAI as ChatGoogleGenerativeAI
            
            self.providers["gemini"] = {
                "class": ChatGoogleGenerativeAI,
                "name": "Gemini (Google)",
                "api_key_env": "GOOGLE_API_KEY",
                "model_env": "GOOGLE_MODEL",
                # Default to latest model: gemini-3-pro-preview (Nov 2025)
                # See https://ai.google.dev/gemini-api/docs/models for all available models
                # Other options: gemini-2.5-flash, gemini-2.0-flash, gemini-2.0-flash-lite
                "default_model": "gemini-3-pro-preview",
                "available": bool(os.getenv("GOOGLE_API_KEY")),
            }
        except ImportError:
            self.providers["gemini"] = {"available": False, "name": "Gemini (Google)"}
        
        # OpenAI
        try:
            from langchain_openai import ChatOpenAI
            self.providers["openai"] = {
                "class": ChatOpenAI,
                "name": "OpenAI",
                "api_key_env": "OPENAI_API_KEY",
                "model_env": "OPENAI_MODEL",
                "default_model": "gpt-4o",
                "available": bool(os.getenv("OPENAI_API_KEY")),
            }
        except ImportError:
            self.providers["openai"] = {"available": False, "name": "OpenAI"}
    
    def get_available_providers(self) -> list[dict]:
        """Get list of available providers with their status."""
        return [
            {
                "id": provider_id,
                "name": info.get("name", provider_id),
                "available": info.get("available", False),
            }
            for provider_id, info in self.providers.items()
        ]
    
    def create_llm(
        self,
        provider: LLMProvider,
        model: Optional[str] = None,
        temperature: float = 0.0,
        tools: Optional[list] = None,
    ) -> BaseChatModel:
        """
        Create an LLM instance for the specified provider.
        
        Args:
            provider: LLM provider ID ("claude", "gemini", or "openai")
            model: Model name (optional, uses default if not provided)
            temperature: Temperature setting (default: 0.0)
            tools: List of tools to bind (optional)
        
        Returns:
            BaseChatModel instance
        
        Raises:
            ValueError: If provider is not available or API key is missing
        """
        if provider not in self.providers:
            raise ValueError(f"Unknown provider: {provider}")
        
        provider_info = self.providers[provider]
        
        if not provider_info.get("available", False):
            raise ValueError(
                f"Provider '{provider}' is not available. "
                f"Please set {provider_info.get('api_key_env', 'API_KEY')} environment variable."
            )
        
        # Get API key
        api_key = os.getenv(provider_info["api_key_env"])
        if not api_key:
            raise ValueError(
                f"API key not found for {provider}. "
                f"Please set {provider_info['api_key_env']} environment variable."
            )
        
        # Get model name
        model_name = model or os.getenv(
            provider_info["model_env"],
            provider_info["default_model"]
        )
        
            # Create LLM instance
            llm_class = provider_info["class"]
            
            try:
                if provider == "claude":
                    llm = llm_class(
                        model=model_name,
                        api_key=api_key,
                        temperature=temperature,
                    )
                elif provider == "gemini":
                    # Try google_api_key first, then api_key
                    try:
                        llm = llm_class(
                            model=model_name,
                            google_api_key=api_key,
                            temperature=temperature,
                        )
                    except TypeError:
                        # Fallback to api_key if google_api_key doesn't work
                        llm = llm_class(
                            model=model_name,
                            api_key=api_key,
                            temperature=temperature,
                        )
                elif provider == "openai":
                    llm = llm_class(
                        model=model_name,
                        api_key=api_key,
                        temperature=temperature,
                    )
                else:
                    raise ValueError(f"Unsupported provider: {provider}")
            
            # Bind tools if provided
            if tools:
                llm = llm.bind_tools(tools=tools)
            
            return llm
            
        except Exception as e:
            raise ValueError(f"Failed to create {provider} LLM: {str(e)}")
    
    def get_default_provider(self) -> Optional[LLMProvider]:
        """Get the default provider (first available)."""
        for provider_id, info in self.providers.items():
            if info.get("available", False):
                return provider_id
        return None
    
    def is_provider_available(self, provider: LLMProvider) -> bool:
        """Check if a provider is available."""
        return self.providers.get(provider, {}).get("available", False)


# Global instance
_llm_provider_manager = None


def get_llm_provider_manager() -> LLMProviderManager:
    """Get the global LLM provider manager instance."""
    global _llm_provider_manager
    if _llm_provider_manager is None:
        _llm_provider_manager = LLMProviderManager()
    return _llm_provider_manager

