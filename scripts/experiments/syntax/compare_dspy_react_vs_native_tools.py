#!/usr/bin/env python3
"""
Compare the live DSPy ReAct tool protocol against provider-native tool calling.

This experiment is intentionally narrow:

1. Capture the exact first-turn prompt/messages that DSPy ReAct generates for the
   benchmark planner path, without requiring a network call.
2. Optionally send one real provider-native tool call through the shared DSPy LM
   factory using the same repo model/provider settings and inspect whether the
   model returns tool_calls.

The goal is to prove whether syntax failures are caused by our prompting or by
DSPy ReAct's own runtime contract.
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import dspy

from controller.agent.benchmark.nodes import BenchmarkPlannerSignature
from controller.agent.config import build_dspy_lm, settings
from controller.agent.prompt_manager import PromptManager

REPO_ROOT = Path(__file__).resolve().parents[3]


class PromptCaptured(RuntimeError):
    """Internal control-flow exception used to stop after prompt capture."""


@dataclass
class CapturedRequest:
    prompt: str | None
    messages: list[dict[str, Any]] | None
    kwargs: dict[str, Any]


class CaptureOnlyLM(dspy.LM):
    """DSPy LM stub that records the first request and exits immediately."""

    def __init__(self) -> None:
        super().__init__(model="capture-only")
        self.captured: CapturedRequest | None = None

    def __call__(
        self,
        prompt: str | None = None,
        messages: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> list[str]:
        self.captured = CapturedRequest(
            prompt=prompt,
            messages=messages,
            kwargs=kwargs,
        )
        raise PromptCaptured("Captured first DSPy request")


def _resolve_litellm_model() -> tuple[str, str | None, str | None]:
    api_base = settings.openai_api_base
    use_openrouter = bool(settings.openrouter_api_key) or bool(
        api_base and "openrouter.ai" in api_base
    )
    model_name = settings.llm_model
    if "/" in model_name and model_name.split("/", 1)[0] in {
        "openai",
        "openrouter",
        "anthropic",
        "azure",
        "gemini",
    }:
        litellm_model = model_name
    elif use_openrouter:
        litellm_model = f"openrouter/{model_name}"
    else:
        litellm_model = f"openai/{model_name}"

    api_key = (
        (settings.openrouter_api_key or settings.openai_api_key)
        if use_openrouter
        else settings.openai_api_key
    )
    return litellm_model, api_key, api_base


def _build_signature() -> type[dspy.Signature]:
    prompt_manager = PromptManager()
    instructions = prompt_manager.render("benchmark_planner")
    return BenchmarkPlannerSignature.with_instructions(instructions)


def _dummy_tools() -> list[Any]:
    def read_file(path: str) -> str:
        """Read one workspace file by relative path."""
        if path == "objectives.yaml":
            return "constraints:\n  max_unit_cost: 12\n"
        return f"# dummy file for {path}\n"

    def write_file(path: str, content: str, overwrite: bool = False) -> str:
        """Create or overwrite one workspace file."""
        return json.dumps(
            {"ok": True, "path": path, "overwrite": overwrite, "bytes": len(content)}
        )

    def submit_plan() -> dict[str, Any]:
        """Validate and submit the planner handoff artifacts."""
        return {
            "ok": True,
            "status": "submitted",
            "errors": [],
            "node_type": "benchmark_planner",
        }

    return [read_file, write_file, submit_plan]


def _react_inputs(task_prompt: str) -> dict[str, str]:
    return {
        "prompt": task_prompt,
        "history": "[]",
        "journal": "No journal entries yet.",
        "review_feedback": "No feedback yet.",
    }


def capture_dspy_react_request(task_prompt: str) -> dict[str, Any]:
    signature = _build_signature()
    program = dspy.ReAct(signature, tools=_dummy_tools(), max_iters=2)
    lm = CaptureOnlyLM()

    try:
        with dspy.settings.context(lm=lm, adapter=dspy.ChatAdapter()):
            program(**_react_inputs(task_prompt))
    except PromptCaptured:
        pass

    if lm.captured is None:
        raise RuntimeError("DSPy request was not captured")

    prompt_text = lm.captured.prompt or ""
    message_text = json.dumps(lm.captured.messages or [], indent=2, ensure_ascii=True)
    return {
        "mode": "capture_dspy_react",
        "has_next_tool_args_text": "next_tool_args" in prompt_text
        or "next_tool_args" in message_text,
        "has_chat_adapter_markers": "[[ ##" in prompt_text or "[[ ##" in message_text,
        "prompt": prompt_text,
        "messages": lm.captured.messages,
        "kwargs": lm.captured.kwargs,
    }


def run_native_tool_call(task_prompt: str) -> dict[str, Any]:
    litellm_model, api_key, api_base = _resolve_litellm_model()
    if not api_key:
        return {
            "mode": "native_tool_call",
            "model": litellm_model,
            "api_base": api_base,
            "error": "No API key configured. Set OPENROUTER_API_KEY or OPENAI_API_KEY.",
        }

    system_prompt = PromptManager().render("benchmark_planner")
    messages = [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": json.dumps(_react_inputs(task_prompt), indent=2),
        },
    ]
    tools = [
        {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "Read one workspace file by relative path.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                    },
                    "required": ["path"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "write_file",
                "description": "Create or overwrite one workspace file.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "content": {"type": "string"},
                        "overwrite": {"type": "boolean"},
                    },
                    "required": ["path", "content"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "submit_plan",
                "description": "Validate and submit the planner handoff artifacts.",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "additionalProperties": False,
                },
            },
        },
    ]

    try:
        native_lm = build_dspy_lm(
            litellm_model,
            session_id="syntax-compare",
            agent_role="syntax_compare",
        ).copy(timeout=60, max_tokens=min(settings.llm_max_tokens, 2048))
        with dspy.settings.context(lm=native_lm, adapter=dspy.ChatAdapter()):
            response = native_lm(
                messages=messages,
                tools=tools,
                tool_choice="auto",
            )
    except Exception as exc:
        return {
            "mode": "native_tool_call",
            "model": litellm_model,
            "api_base": api_base,
            "error": f"{type(exc).__name__}: {exc}",
        }

    choice = response.choices[0]
    message = choice.message
    tool_calls = []
    for tool_call in getattr(message, "tool_calls", []) or []:
        function = getattr(tool_call, "function", None)
        tool_calls.append(
            {
                "id": getattr(tool_call, "id", None),
                "type": getattr(tool_call, "type", None),
                "name": getattr(function, "name", None) if function else None,
                "arguments": (
                    getattr(function, "arguments", None) if function else None
                ),
            }
        )

    return {
        "mode": "native_tool_call",
        "model": litellm_model,
        "api_base": api_base,
        "content": getattr(message, "content", None),
        "tool_calls": tool_calls,
        "finish_reason": getattr(choice, "finish_reason", None),
        "reasoning_content": getattr(message, "reasoning_content", None),
        "usage": getattr(response, "usage", None),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mode",
        choices=["capture-react", "native", "both"],
        default="both",
        help="Which experiment branch to run.",
    )
    parser.add_argument(
        "--task-prompt",
        default=(
            "Create a simple benchmark where a ball must roll sideways into a goal "
            "zone using only static geometry."
        ),
        help="Benchmark planner task prompt to feed into the experiment.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional JSON output path.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    results: list[dict[str, Any]] = []

    if args.mode in {"capture-react", "both"}:
        results.append(capture_dspy_react_request(args.task_prompt))

    if args.mode in {"native", "both"}:
        results.append(run_native_tool_call(args.task_prompt))

    payload = {
        "cwd": str(REPO_ROOT),
        "pid": os.getpid(),
        "results": results,
    }
    text = json.dumps(payload, indent=2, default=str)
    print(text)

    if args.output:
        args.output.write_text(text + "\n", encoding="utf-8")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
