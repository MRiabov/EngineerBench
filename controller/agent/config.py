import threading
import time
from collections import deque
from functools import lru_cache
from typing import Any, Literal

import dspy
import structlog
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from controller.config.settings import settings as global_settings
from shared.agents.config import load_agents_config

logger = structlog.get_logger(__name__)


def _load_agents_llm_config():
    return load_agents_config().llm


class LiteLLMRequestConfig(BaseModel):
    """Resolved DSPy request settings for one model invocation."""

    model: str
    api_key: str | None
    api_base: str | None
    provider: Literal["openrouter", "openai_compatible", "gemini"]


_DIRECT_PROVIDER_PREFIXES = {
    "openai",
    "openrouter",
    "anthropic",
    "azure",
    "gemini",
}

_GOOGLE_AI_STUDIO_V1BETA_BASE = "https://generativelanguage.googleapis.com/v1beta"


class AgentSettings(BaseSettings):
    """Configuration for the Engineer Agent."""

    llm_model: str = global_settings.llm_model
    openai_api_key: str | None = None
    openai_api_base: str | None = None  # For OpenRouter or custom endpoints
    openrouter_api_key: str | None = global_settings.openrouter_api_key
    anthropic_api_key: str | None = None
    llm_timeout_seconds: int = 300
    native_tool_completion_timeout_seconds: int = 60
    llm_max_tokens: int = _load_agents_llm_config().max_reasoning_tokens
    context_compaction_threshold_tokens: int = (
        _load_agents_llm_config().context_compaction_threshold_tokens
    )
    llm_requests_per_minute: int = Field(
        default=_load_agents_llm_config().requests_per_minute,
        alias="LLM_REQUESTS_PER_MINUTE",
    )
    dspy_program_timeout_seconds: int = 300
    dspy_program_max_retries: int = 2
    require_reasoning_traces: bool = global_settings.require_reasoning_traces

    # URL for the Worker Light API
    worker_light_url: str = global_settings.worker_light_url
    worker_heavy_url: str | None = global_settings.worker_heavy_url
    is_integration_test: bool = global_settings.is_integration_test

    # DB connection for checkpointing (if using PostgresSaver in future)
    db_connection_string: str | None = None

    # Default session/thread ID for the agent
    default_session_id: str = "00000000-0000-0000-0000-000000000000"

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    def uses_openrouter(self, model_name: str | None = None) -> bool:
        api_base = self.openai_api_base
        if api_base and "openrouter.ai" in api_base:
            return True

        if model_name:
            if model_name.startswith("openrouter/"):
                return True
            model_prefix = model_name.split("/", 1)[0] if "/" in model_name else None
            if model_prefix in _DIRECT_PROVIDER_PREFIXES:
                return False

        return bool(self.openrouter_api_key)

    def resolve_dspy_lm_request_config(self, model_name: str) -> LiteLLMRequestConfig:
        api_base = self.openai_api_base
        use_openrouter = self.uses_openrouter(model_name)
        prefix = model_name.split("/", 1)[0] if "/" in model_name else None
        is_direct_gemini = model_name.startswith("gemini/")

        if use_openrouter:
            if model_name.startswith("openrouter/"):
                # LiteLLM's OpenRouter adapter expects the provider namespace to
                # remain explicit for cloaked models like `openrouter/healer-alpha`.
                # Those arrive as a one-segment OpenRouter slug and need the extra
                # `openrouter/` layer preserved for the provider router.
                if model_name.count("/") == 1:
                    litellm_model = f"openrouter/{model_name}"
                else:
                    litellm_model = model_name
            else:
                normalized_model = model_name
                # Preserve the existing direct-Gemini env shape while routing
                # through OpenRouter, whose Gemini models use the `google/...`
                # provider namespace.
                if model_name.startswith("gemini/"):
                    normalized_model = f"google/{model_name.split('/', 1)[1]}"
                litellm_model = f"openrouter/{normalized_model}"
        elif prefix in _DIRECT_PROVIDER_PREFIXES:
            litellm_model = model_name
        else:
            litellm_model = f"openai/{model_name}"

        if use_openrouter:
            api_key = self.openrouter_api_key or self.openai_api_key
            provider: Literal["openrouter", "openai_compatible", "gemini"] = (
                "openrouter"
            )
            resolved_api_base = api_base
        elif is_direct_gemini:
            # Route direct Gemini through the documented AI Studio beta endpoint
            # instead of LiteLLM's Gemini 3 alpha default.
            api_key = self.openai_api_key
            provider = "gemini"
            resolved_api_base = api_base or _GOOGLE_AI_STUDIO_V1BETA_BASE
        else:
            api_key = self.openai_api_key
            provider = "openai_compatible"
            resolved_api_base = api_base

        return LiteLLMRequestConfig(
            model=litellm_model,
            api_key=api_key,
            api_base=resolved_api_base,
            provider=provider,
        )

    def resolve_litellm_request_config(self, model_name: str) -> LiteLLMRequestConfig:
        """Backward-compatible alias for the DSPy request resolver."""
        return self.resolve_dspy_lm_request_config(model_name)


settings = AgentSettings()


class _SlidingWindowRateLimiter:
    """Thread-safe per-process RPM limiter with queue-and-wait behavior."""

    def __init__(self, requests_per_minute: int):
        self._rpm = max(1, int(requests_per_minute))
        self._window_seconds = 60.0
        self._timestamps: deque[float] = deque()
        self._lock = threading.Lock()

    def acquire(self) -> float:
        """Block until a request slot is available; return total wait time."""
        waited_seconds = 0.0
        while True:
            with self._lock:
                now = time.monotonic()
                cutoff = now - self._window_seconds
                while self._timestamps and self._timestamps[0] <= cutoff:
                    self._timestamps.popleft()

                if len(self._timestamps) < self._rpm:
                    self._timestamps.append(now)
                    return waited_seconds

                oldest = self._timestamps[0]
                sleep_for = max(0.0, self._window_seconds - (now - oldest))

            if sleep_for > 0.0:
                time.sleep(sleep_for)
                waited_seconds += sleep_for


_limiter = _SlidingWindowRateLimiter(settings.llm_requests_per_minute)


def _is_transient_provider_rate_error(error: Exception) -> bool:
    text = str(error).lower()
    markers = (
        "ratelimiterror",
        "resource_exhausted",
        '"code": 429',
        'status": "resource_exhausted"',
        "too many requests",
        '"code": 503',
        "service unavailable",
    )
    return any(marker in text for marker in markers)


class RateLimitedDSPyLM(dspy.LM):
    """DSPy LM subclass that adds process-local RPM limiting."""

    def __init__(self, *args: Any, node_type: str, session_id: str, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self.node_type = node_type
        self.session_id = session_id

    def forward(
        self,
        prompt: str | None = None,
        messages: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> Any:
        wait_seconds = _limiter.acquire()
        if wait_seconds > 0.0:
            logger.info(
                "llm_rate_limit_wait",
                node_type=self.node_type,
                session_id=self.session_id,
                wait_seconds=round(wait_seconds, 3),
                requests_per_minute=settings.llm_requests_per_minute,
                model=getattr(self, "model", None),
            )
        request_kwargs = dict(kwargs)
        try:
            return super().forward(prompt=prompt, messages=messages, **request_kwargs)
        except Exception as error:
            if _is_transient_provider_rate_error(error):
                logger.error(
                    "llm_provider_rate_limited",
                    node_type=self.node_type,
                    session_id=self.session_id,
                    error=str(error),
                )
            raise


@lru_cache(maxsize=16)
def _build_cached_dspy_lm(
    model: str,
    api_key: str,
    api_base: str | None,
    timeout_seconds: int,
    max_tokens: int,
    num_retries: int,
    reasoning_effort: str | None = None,
) -> RateLimitedDSPyLM:
    lm_kwargs: dict[str, Any] = {
        "api_key": api_key,
        "cache": False,
        "timeout": timeout_seconds,
        "max_tokens": max_tokens,
        "num_retries": num_retries,
    }
    if reasoning_effort is not None:
        lm_kwargs["reasoning_effort"] = reasoning_effort
    if api_base:
        lm_kwargs["api_base"] = api_base

    return RateLimitedDSPyLM(
        model,
        **lm_kwargs,
        node_type="shared",
        session_id=settings.default_session_id,
    )


def build_dspy_lm(
    model_name: str | None = None,
    *,
    session_id: str | None = None,
    agent_role: str | None = None,
) -> Any:
    if settings.is_integration_test:
        from controller.agent.mock_llm import MockDSPyLM

        return MockDSPyLM(session_id=session_id, node_type=agent_role)

    resolved_model = model_name or settings.llm_model
    request_config = settings.resolve_dspy_lm_request_config(resolved_model)
    api_key = request_config.api_key or "dummy"
    reasoning_effort = (
        load_agents_config().get_reasoning_effort(agent_role)
        if agent_role is not None
        else None
    )
    base_lm = _build_cached_dspy_lm(
        request_config.model,
        api_key,
        request_config.api_base,
        settings.llm_timeout_seconds,
        settings.llm_max_tokens,
        settings.dspy_program_max_retries,
        reasoning_effort,
    )
    lm = base_lm.copy()
    lm.node_type = agent_role or "unknown_node"
    lm.session_id = session_id or settings.default_session_id
    return lm
