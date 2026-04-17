#!/usr/bin/env python3
"""Probe whether DSPy ReAct can avoid next_tool_* and compare with native tools."""

from __future__ import annotations

import argparse
import inspect
import json
import os
from typing import Any

import dspy

from controller.agent.config import build_dspy_lm


def fake_write_file(path: str, content: str, overwrite: bool = False) -> str:
    """Fake tool used only for syntax probing."""
    return (
        f"fake write_file called path={path!r} content_len={len(content)} "
        f"overwrite={overwrite}"
    )


class ProbeSignature(dspy.Signature):
    """Minimal tool-using signature for DSPy ReAct inspection."""

    question = dspy.InputField()
    answer = dspy.OutputField()


def _adapter_defaults(adapter: Any) -> dict[str, Any]:
    return {
        "class": type(adapter).__name__,
        "use_native_function_calling": getattr(
            adapter, "use_native_function_calling", None
        ),
        "use_json_adapter_fallback": getattr(
            adapter, "use_json_adapter_fallback", None
        ),
    }


def inspect_dspy_react() -> dict[str, Any]:
    react = dspy.ReAct(ProbeSignature, tools=[fake_write_file], max_iters=2)
    react_signature = react.react.signature
    instructions = getattr(react_signature, "instructions", "") or ""
    output_fields = list(react_signature.output_fields.keys())
    force_fields = {"next_thought", "next_tool_name", "next_tool_args"}
    react_source = inspect.getsource(type(react))
    interesting_source_lines = []
    for idx, line in enumerate(react_source.splitlines(), 1):
        if any(
            token in line
            for token in (
                "next_thought",
                "next_tool_name",
                "next_tool_args",
                "interleave",
            )
        ):
            interesting_source_lines.append(f"{idx}: {line.rstrip()}")

    return {
        "dspy_version": getattr(dspy, "__version__", "unknown"),
        "react_signature_output_fields": output_fields,
        "react_forces_next_tool_fields": force_fields.issubset(output_fields),
        "react_instruction_excerpt": [
            line.strip()
            for line in instructions.splitlines()
            if "next_" in line or "interleave" in line
        ],
        "chat_adapter_default": _adapter_defaults(dspy.ChatAdapter()),
        "chat_adapter_fail_closed": _adapter_defaults(
            dspy.ChatAdapter(use_json_adapter_fallback=False)
        ),
        "json_adapter_default": _adapter_defaults(dspy.JSONAdapter()),
        "react_source_lines": interesting_source_lines,
    }


def _provider_credentials() -> tuple[str | None, str | None]:
    try:
        from controller.config.settings import settings as global_settings

        return (
            global_settings.openrouter_api_key or global_settings.openai_api_key,
            global_settings.openai_api_base,
        )
    except Exception:
        return (os.getenv("OPENROUTER_API_KEY"), os.getenv("OPENAI_API_BASE"))


def run_dspy_native_tool_probe(model: str) -> dict[str, Any]:
    api_key, _api_base = _provider_credentials()
    if not api_key:
        return {"skipped": True, "reason": "No API key configured for DSPy LM probe"}

    signature = dspy.Signature("question ->")
    signature = signature.append("tools", dspy.InputField(), type_=list[dspy.Tool])
    signature = signature.append("tool_calls", dspy.OutputField(), type_=dspy.ToolCalls)

    lm = build_dspy_lm(
        f"openrouter/{model}",
        session_id="syntax-probe",
        agent_role="syntax_probe",
    ).copy(timeout=60, max_tokens=512)
    predict = dspy.Predict(signature)
    tool = dspy.Tool(fake_write_file)
    adapter = dspy.ChatAdapter(
        use_native_function_calling=True,
        use_json_adapter_fallback=False,
    )

    with dspy.settings.context(lm=lm, adapter=adapter):
        prediction = predict(
            question=(
                "Call write_file once with path note.txt, content hi, overwrite true. "
                "Do not explain."
            ),
            tools=[tool],
        )

    tool_calls = getattr(prediction, "tool_calls", None)
    normalized_calls: list[dict[str, Any]] = []
    if isinstance(tool_calls, dspy.ToolCalls):
        for call in tool_calls.tool_calls:
            normalized_calls.append({"name": call.name, "args": call.args})

    return {
        "skipped": False,
        "tool_calls_present": bool(normalized_calls),
        "tool_calls": normalized_calls,
    }


def run_openrouter_native_tool_probe(model: str) -> dict[str, Any]:
    api_key, _api_base = _provider_credentials()
    if not api_key:
        return {
            "skipped": True,
            "reason": "No API key configured for OpenRouter probe",
        }

    lm = build_dspy_lm(
        f"openrouter/{model}",
        session_id="syntax-probe",
        agent_role="syntax_probe",
    ).copy(timeout=60)
    response = lm(
        messages=[
            {
                "role": "user",
                "content": (
                    "Call the write_file tool once with path note.txt, content hi, "
                    "overwrite true. Do not explain."
                ),
            }
        ],
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "write_file",
                    "description": "Write content to a file.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string"},
                            "content": {"type": "string"},
                            "overwrite": {"type": "boolean"},
                        },
                        "required": ["path", "content", "overwrite"],
                    },
                },
            }
        ],
        tool_choice="required",
    )

    message = response.choices[0].message
    raw_tool_calls = getattr(message, "tool_calls", None)
    normalized_calls: list[dict[str, Any]] = []
    if raw_tool_calls:
        for call in raw_tool_calls:
            function = getattr(call, "function", None)
            normalized_calls.append(
                {
                    "id": getattr(call, "id", None),
                    "type": getattr(call, "type", None),
                    "name": getattr(function, "name", None),
                    "arguments": getattr(function, "arguments", None),
                }
            )

    return {
        "skipped": False,
        "tool_calls_present": bool(raw_tool_calls),
        "tool_calls": normalized_calls,
        "content": getattr(message, "content", None),
        "reasoning_content_present": bool(getattr(message, "reasoning_content", None)),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--live-dspy-native",
        action="store_true",
        help="Run a live DSPy Predict + ToolCalls probe without using dspy.ReAct.",
    )
    parser.add_argument(
        "--live-openrouter",
        action="store_true",
        help="Also run a direct provider-native tool call through OpenRouter.",
    )
    parser.add_argument(
        "--model",
        default="google/gemini-2.5-flash",
        help="Provider model slug for the direct OpenRouter probe.",
    )
    args = parser.parse_args()

    report: dict[str, Any] = {
        "dspy_react_probe": inspect_dspy_react(),
    }

    if args.live_dspy_native:
        report["dspy_native_tool_probe"] = run_dspy_native_tool_probe(args.model)

    if args.live_openrouter:
        report["openrouter_native_tool_probe"] = run_openrouter_native_tool_probe(
            args.model
        )

    print(json.dumps(report, indent=2, sort_keys=False))


if __name__ == "__main__":
    main()
