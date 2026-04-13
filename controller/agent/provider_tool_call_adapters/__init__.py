from .base import ParsedToolCalls, ProviderToolCallAdapter
from .native_adapter import NativeToolCallAdapter

_ADAPTERS: tuple[ProviderToolCallAdapter, ...] = (NativeToolCallAdapter(),)


def extract_tool_calls(
    message: object,
    *,
    assistant_text: str,
    model_name: str | None = None,
) -> ParsedToolCalls:
    for adapter in _ADAPTERS:
        if not adapter.should_attempt(
            assistant_text=assistant_text,
            model_name=model_name,
        ):
            continue
        parsed = adapter.extract(
            message=message,
            assistant_text=assistant_text,
            model_name=model_name,
        )
        if parsed.tool_calls:
            return parsed
    return ParsedToolCalls(assistant_text=assistant_text, tool_calls=[])


__all__ = [
    "ParsedToolCalls",
    "ProviderToolCallAdapter",
    "extract_tool_calls",
]
