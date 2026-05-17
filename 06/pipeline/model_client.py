"""Unified LLM calling client module.

Supports DeepSeek, Qwen, and OpenAI providers via OpenAI-compatible APIs.
Uses httpx for direct HTTP calls without the openai SDK dependency.

Provider configs are loaded from .env file with the following variables:
    LLM_PROVIDER: Active provider name (deepseek/qwen/openai), default "deepseek".
    {PROVIDER}_BASE_URL: API base URL for the provider.
    {PROVIDER}_API_KEY: API key for the provider.
    {PROVIDER}_DEFAULT_MODEL: Default model name for the provider.
"""

import logging
import math
import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import httpx
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

logger = logging.getLogger(__name__)

_DEFAULTS: dict[str, dict[str, str]] = {
    "deepseek": {
        "base_url": "https://api.deepseek.com/v1",
        "api_key_env": "DEEPSEEK_API_KEY",
        "default_model": "deepseek-v4-flash",
    },
    "qwen": {
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "api_key_env": "QWEN_API_KEY",
        "default_model": "qwen3.5-flash",
    },
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "api_key_env": "OPENAI_API_KEY",
        "default_model": "gpt-4o",
    },
}

_PROVIDER_ENV_KEYS: dict[str, dict[str, str]] = {
    "deepseek": {
        "base_url": "DEEPSEEK_BASE_URL",
        "default_model": "DEEPSEEK_DEFAULT_MODEL",
    },
    "qwen": {
        "base_url": "QWEN_BASE_URL",
        "default_model": "QWEN_DEFAULT_MODEL",
    },
    "openai": {
        "base_url": "OPENAI_BASE_URL",
        "default_model": "OPENAI_DEFAULT_MODEL",
    },
}


def _load_provider_configs() -> dict[str, dict[str, str]]:
    """Build provider configs by reading .env with hardcoded fallbacks.

    Reads {PROVIDER}_BASE_URL and {PROVIDER}_DEFAULT_MODEL from environment
    variables (loaded via dotenv). Falls back to built-in defaults.

    Returns:
        Provider config dict keyed by provider name.
    """
    configs: dict[str, dict[str, str]] = {}
    for provider, defaults in _DEFAULTS.items():
        env_keys = _PROVIDER_ENV_KEYS[provider]
        base_url = os.getenv(env_keys["base_url"], defaults["base_url"])
        default_model = os.getenv(env_keys["default_model"], defaults["default_model"])
        configs[provider] = {
            "base_url": base_url,
            "api_key_env": defaults["api_key_env"],
            "default_model": default_model,
        }
    return configs


PROVIDER_CONFIGS: dict[str, dict[str, str]] = _load_provider_configs()

PRICING_TABLE: dict[str, dict[str, float]] = {
    "deepseek-v4-flash": {"input": 0.14 / 1_000_000, "output": 0.28 / 1_000_000},
    "deepseek-v4-pro": {"input": 0.55 / 1_000_000, "output": 2.19 / 1_000_000},
    "qwen3.5-flash": {"input": 0.30 / 1_000_000, "output": 0.60 / 1_000_000},
    "qwen3.6-flash": {"input": 0.80 / 1_000_000, "output": 2.00 / 1_000_000},
    "gpt-4o": {"input": 2.50 / 1_000_000, "output": 10.00 / 1_000_000},
    "gpt-4o-mini": {"input": 0.15 / 1_000_000, "output": 0.60 / 1_000_000},
}

DEFAULT_TIMEOUT = 60.0
MAX_RETRIES = 3


@dataclass
class Usage:
    """Token usage statistics from an LLM response.

    Attributes:
        prompt_tokens: Number of tokens in the prompt.
        completion_tokens: Number of tokens in the completion.
        total_tokens: Total tokens used (prompt + completion).
    """

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass
class LLMResponse:
    """Unified response from an LLM provider.

    Attributes:
        content: The generated text content.
        usage: Token usage statistics.
        model: The model name that generated the response.
        provider: The provider name that generated the response.
    """

    content: str = ""
    usage: Usage = field(default_factory=Usage)
    model: str = ""
    provider: str = ""


class LLMProvider(ABC):
    """Abstract base class defining the LLM provider interface."""

    @abstractmethod
    def chat(
        self,
        messages: list[dict[str, str]],
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        **kwargs: Any,
    ) -> LLMResponse:
        """Send a chat completion request.

        Args:
            messages: List of message dicts with 'role' and 'content' keys.
            model: Model name override. Uses provider default if None.
            temperature: Sampling temperature, between 0 and 2.
            max_tokens: Maximum tokens to generate.
            **kwargs: Additional parameters passed to the API.

        Returns:
            LLMResponse with content, usage, model, and provider info.
        """


class OpenAICompatibleProvider(LLMProvider):
    """Provider that calls OpenAI-compatible chat completion APIs via httpx.

    This provider works with any service that implements the OpenAI chat
    completion API format, including DeepSeek and Qwen (DashScope).

    Args:
        provider_name: Provider identifier (deepseek/qwen/openai).
        api_key: API key for authentication.
        base_url: Base URL for the API endpoint.
        default_model: Default model name to use.
    """

    def __init__(
        self,
        provider_name: str,
        api_key: str,
        base_url: str,
        default_model: str,
    ) -> None:
        self.provider_name = provider_name
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.default_model = default_model

    def chat(
        self,
        messages: list[dict[str, str]],
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        **kwargs: Any,
    ) -> LLMResponse:
        """Send a chat completion request to an OpenAI-compatible API.

        Args:
            messages: List of message dicts with 'role' and 'content' keys.
            model: Model name override. Uses provider default if None.
            temperature: Sampling temperature, between 0 and 2.
            max_tokens: Maximum tokens to generate.
            **kwargs: Additional parameters passed to the API.

        Returns:
            LLMResponse with content, usage, model, and provider info.

        Raises:
            httpx.HTTPStatusError: If the API returns a non-2xx status code.
            httpx.TimeoutException: If the request times out.
        """
        model = model or self.default_model
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            **kwargs,
        }

        logger.debug(
            "Sending request to %s provider=%s model=%s",
            url,
            self.provider_name,
            model,
        )

        with httpx.Client(timeout=DEFAULT_TIMEOUT) as client:
            resp = client.post(url, json=payload, headers=headers)
            resp.raise_for_status()

        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        usage_data = data.get("usage", {})
        usage = Usage(
            prompt_tokens=usage_data.get("prompt_tokens", 0),
            completion_tokens=usage_data.get("completion_tokens", 0),
            total_tokens=usage_data.get("total_tokens", 0),
        )

        logger.info(
            "Received response from %s model=%s prompt_tokens=%d completion_tokens=%d",
            self.provider_name,
            model,
            usage.prompt_tokens,
            usage.completion_tokens,
        )

        return LLMResponse(
            content=content,
            usage=usage,
            model=model,
            provider=self.provider_name,
        )


def create_provider(
    provider_name: Optional[str] = None,
    api_key: Optional[str] = None,
) -> OpenAICompatibleProvider:
    """Factory function to create an LLM provider from environment variables.

    Reads LLM_PROVIDER env var for the provider name and the corresponding
    API key env var. Falls back to defaults if not set.

    Args:
        provider_name: Provider name override. Defaults to LLM_PROVIDER env var
            or "deepseek".
        api_key: API key override. Defaults to the provider-specific env var.

    Returns:
        A configured OpenAICompatibleProvider instance.

    Raises:
        ValueError: If no API key is found for the specified provider.
    """
    provider_name = provider_name or os.getenv("LLM_PROVIDER", "deepseek")
    config = PROVIDER_CONFIGS.get(provider_name)
    if config is None:
        raise ValueError(
            f"Unknown provider: {provider_name}. "
            f"Supported: {list(PROVIDER_CONFIGS.keys())}"
        )

    api_key = api_key or os.getenv(config["api_key_env"], "")
    if not api_key:
        raise ValueError(
            f"API key not found. Set the {config['api_key_env']} environment variable."
        )

    return OpenAICompatibleProvider(
        provider_name=provider_name,
        api_key=api_key,
        base_url=config["base_url"],
        default_model=config["default_model"],
    )


def chat_with_retry(
    messages: list[dict[str, str]],
    provider: Optional[LLMProvider] = None,
    model: Optional[str] = None,
    temperature: float = 0.7,
    max_tokens: int = 2048,
    max_retries: int = MAX_RETRIES,
    **kwargs: Any,
) -> LLMResponse:
    """Send a chat request with exponential backoff retry logic.

    Retries on transient errors (5xx, timeout, connection errors) up to
    max_retries times with exponential backoff (1s, 2s, 4s, ...).

    Args:
        messages: List of message dicts with 'role' and 'content' keys.
        provider: LLM provider instance. Creates one from env if None.
        model: Model name override.
        temperature: Sampling temperature.
        max_tokens: Maximum tokens to generate.
        max_retries: Maximum number of retry attempts.
        **kwargs: Additional parameters passed to the provider chat method.

    Returns:
        LLMResponse from the successful API call.

    Raises:
        httpx.HTTPStatusError: If all retries are exhausted on API errors.
    """
    provider = provider or create_provider()
    last_exception: Optional[Exception] = None

    for attempt in range(1, max_retries + 1):
        try:
            return provider.chat(
                messages=messages,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                **kwargs,
            )
        except (httpx.TimeoutException, httpx.ConnectError) as exc:
            last_exception = exc
            backoff = 2 ** (attempt - 1)
            logger.warning(
                "Request failed (attempt %d/%d): %s. Retrying in %ds...",
                attempt,
                max_retries,
                exc,
                backoff,
            )
            time.sleep(backoff)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code >= 500:
                last_exception = exc
                backoff = 2 ** (attempt - 1)
                logger.warning(
                    "Server error %d (attempt %d/%d). Retrying in %ds...",
                    exc.response.status_code,
                    attempt,
                    max_retries,
                    backoff,
                )
                time.sleep(backoff)
            else:
                raise

    raise last_exception  # type: ignore[misc]


def estimate_tokens(text: str) -> int:
    """Estimate the number of tokens in a text string.

    Uses the heuristic of ~4 characters per token, which is a reasonable
    approximation for English text. Chinese text may use more tokens.

    Args:
        text: The input text to estimate tokens for.

    Returns:
        Estimated token count.
    """
    return math.ceil(len(text) / 4)


def calculate_cost(
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
) -> float:
    """Calculate the estimated cost in USD for an LLM API call.

    Args:
        model: The model name used for the call.
        prompt_tokens: Number of input tokens.
        completion_tokens: Number of output tokens.

    Returns:
        Estimated cost in USD. Returns 0.0 if the model is not in the
        pricing table.
    """
    pricing = PRICING_TABLE.get(model)
    if pricing is None:
        logger.warning("No pricing data for model %s, cost=0.0", model)
        return 0.0

    input_cost = prompt_tokens * pricing["input"]
    output_cost = completion_tokens * pricing["output"]
    return round(input_cost + output_cost, 8)


def quick_chat(
    prompt: str,
    system: str = "You are a helpful assistant.",
    provider: Optional[LLMProvider] = None,
    model: Optional[str] = None,
    temperature: float = 0.7,
    max_tokens: int = 2048,
) -> LLMResponse:
    """Convenient one-shot function to call an LLM with a single prompt.

    Wraps chat_with_retry with a simple string interface instead of
    manually constructing message lists.

    Args:
        prompt: The user message to send.
        system: System prompt. Defaults to a generic helpful assistant.
        provider: LLM provider instance. Creates one from env if None.
        model: Model name override.
        temperature: Sampling temperature.
        max_tokens: Maximum tokens to generate.

    Returns:
        LLMResponse containing the generated text and usage info.
    """
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": prompt},
    ]
    return chat_with_retry(
        messages=messages,
        provider=provider,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
    )


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    print("=== model_client.py Test ===\n")

    print("--- Provider Configs ---")
    for name, conf in PROVIDER_CONFIGS.items():
        print(f"  {name}: base_url={conf['base_url']}, model={conf['default_model']}")

    print("\n--- Token Estimation ---")
    samples = [
        "Hello, world!",
        "This is a longer sentence to test token estimation accuracy.",
        "这是一个用来测试中文 token 估算的句子。",
    ]
    for s in samples:
        print(f"  {s!r} => ~{estimate_tokens(s)} tokens")

    print("\n--- Cost Calculation ---")
    cost_cases = [
        ("deepseek-chat", 1000, 500),
        ("gpt-4o", 2000, 1000),
        ("qwen-plus", 500, 200),
        ("unknown-model", 100, 50),
    ]
    for mdl, pt, ct in cost_cases:
        cost = calculate_cost(mdl, pt, ct)
        print(f"  {mdl}: {pt}in + {ct}out = ${cost:.8f}")

    print("\n--- create_provider() ---")
    for prov in ("deepseek", "qwen", "openai"):
        has_key = bool(os.getenv(PROVIDER_CONFIGS[prov]["api_key_env"]))
        print(f"  {prov}: API key {'set' if has_key else 'NOT set'}")

    active_provider = os.getenv("LLM_PROVIDER", "deepseek")
    print(f"  Active provider: {active_provider}")

    try:
        prov = create_provider()
        print(f"  Created provider: {prov.provider_name} @ {prov.base_url}")
    except ValueError as e:
        print(f"  Cannot create provider: {e}")

    print("\n--- quick_chat() Demo ---")
    if bool(os.getenv(PROVIDER_CONFIGS.get(active_provider, {}).get("api_key_env", ""))):
        print("  Calling LLM (this may take a few seconds)...")
        try:
            resp = quick_chat("Say hello in one sentence.")
            print(f"  Response: {resp.content}")
            print(f"  Model: {resp.model}, Provider: {resp.provider}")
            print(
                f"  Usage: {resp.usage.prompt_tokens}in / "
                f"{resp.usage.completion_tokens}out / "
                f"{resp.usage.total_tokens}total"
            )
            cost = calculate_cost(
                resp.model,
                resp.usage.prompt_tokens,
                resp.usage.completion_tokens,
            )
            print(f"  Estimated cost: ${cost:.8f}")
        except Exception as e:
            print(f"  Error: {e}")
    else:
        env_var = PROVIDER_CONFIGS[active_provider]["api_key_env"]
        print(f"  Skipped: no {env_var} environment variable set.")

    print("\n=== Tests Complete ===")