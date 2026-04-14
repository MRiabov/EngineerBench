import asyncio
import hashlib
import inspect
import json
import re
import time
import uuid
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import dspy
import httpx
import structlog
import yaml
from langchain_core.messages import AIMessage, HumanMessage

from controller.agent.config import (
    LiteLLMRequestConfig,
    _is_transient_provider_rate_error,
    build_dspy_lm,
    settings,
)
from controller.agent.nodes.base import BaseNode, SharedNodeContext
from controller.agent.tools import filter_tools_for_agent
from controller.observability.tracing import record_worker_events
from shared.enums import AgentName, ReviewDecision, SessionStatus
from shared.models.schemas import ReviewResult
from shared.models.simulation import SimulationResult
from shared.observability.schemas import ReviewDecisionEvent
from shared.script_contracts import (
    BENCHMARK_PLAN_PATH,
    BENCHMARK_SCRIPT_PATH,
)
from shared.simulation.schemas import (
    RandomizationStrategy,
    SimulatorBackendType,
    get_default_simulator_backend,
)
from shared.type_checking import type_check
from shared.workers.schema import SimulationArtifacts, ValidationResultRecord

from ..benchmark_handover_validation import (
    BenchmarkPlanReviewerEvidence,
)
from ..nodes.cots_search import COTSSearchNode
from ..review_handover import (
    collect_plan_reviewer_handover_evidence,
    validate_reviewer_handover,
)
from .state import BenchmarkGeneratorState
from .tools import get_benchmark_planner_tools, get_benchmark_tools

logger = structlog.get_logger(__name__)
_NATIVE_TOOL_COMPLETION_MAX_TOKENS = 1024
_SYSTEM_TOOL_RETRY_EXHAUSTED_MARKER = "SYSTEM_TOOL_RETRY_EXHAUSTED"

BENCHMARK_DEFINITION_FILE = "benchmark_definition.yaml"
SCRIPT_FILE = BENCHMARK_SCRIPT_PATH
PLAN_FILE = BENCHMARK_PLAN_PATH


def _benchmark_worker_session_id(state: BenchmarkGeneratorState) -> str:
    worker_session_id = (state.worker_session_id or "").strip()
    if worker_session_id:
        return worker_session_id
    return str(state.session.session_id)


def extract_python_code(text: str) -> str:
    """Extracts python code block from markdown."""
    pattern = r"```python\n(.*?)\n```"
    match = re.search(pattern, text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return text.strip()


def _script_contract_violations(script: str) -> list[str]:
    """Return benchmark script contract violations that must fail closed."""
    violations: list[str] = []
    if 'if __name__ == "__main__"' in script or "if __name__ == '__main__'" in script:
        violations.append(f"{SCRIPT_FILE} must not contain a __main__ block")

    return list(dict.fromkeys(violations))


class BenchmarkPlannerSignature(dspy.Signature):
    """DSPy signature for the benchmark planner."""

    prompt = dspy.InputField()
    history = dspy.InputField()
    journal = dspy.InputField()
    review_feedback = dspy.InputField()
    reasoning = dspy.OutputField()
    plan = dspy.OutputField(
        desc=("High-level randomization strategy summary. Can be plain text or JSON.")
    )


@dataclass
class NativePlannerPrediction:
    reasoning: str
    plan: dict[str, Any]


def _extract_markdown_section(markdown: str, heading: str) -> str:
    if not markdown.strip():
        return ""

    pattern = rf"{re.escape(heading)}\s*\n(.*?)(?=\n##\s+\d+\.|\Z)"
    match = re.search(pattern, markdown, flags=re.DOTALL)
    if not match:
        return ""
    return match.group(1).strip()


@type_check
class BenchmarkPlannerNode(BaseNode):
    """Refactored Benchmark Planner using BaseNode for prompt injection."""

    async def __call__(self, state: BenchmarkGeneratorState) -> BenchmarkGeneratorState:
        # Init Git
        await self.ctx.worker_client.git_init()

        # Custom Objectives Logic
        custom_objectives = state.session.custom_objectives
        if custom_objectives:
            logger.info(
                "planner_updating_objectives", session_id=state.session.session_id
            )
            try:
                from worker_heavy.utils.file_validation import (
                    validate_benchmark_definition_yaml,
                )

                obj_content = await self.ctx.worker_client.read_file_optional(
                    BENCHMARK_DEFINITION_FILE
                )
                if obj_content is not None:
                    is_valid, obj_result = validate_benchmark_definition_yaml(
                        obj_content,
                        session_id=str(state.session.session_id),
                    )
                    if not is_valid:
                        raise ValueError("; ".join(obj_result))
                    obj_data = obj_result

                    # Update constraints based on custom objectives
                    if custom_objectives.max_unit_cost is not None:
                        obj_data.constraints.max_unit_cost = (
                            custom_objectives.max_unit_cost
                        )
                        obj_data.constraints.estimated_solution_cost_usd = (
                            custom_objectives.max_unit_cost / 1.5
                        )
                    if custom_objectives.max_weight is not None:
                        obj_data.constraints.max_weight_g = custom_objectives.max_weight
                        obj_data.constraints.estimated_solution_weight_g = (
                            custom_objectives.max_weight / 1.5
                        )
                    if custom_objectives.target_quantity is not None:
                        obj_data.constraints.target_quantity = (
                            custom_objectives.target_quantity
                        )

                    new_content = yaml.dump(
                        obj_data.model_dump(mode="json"), sort_keys=False
                    )
                    await self.ctx.worker_client.write_file(
                        BENCHMARK_DEFINITION_FILE, new_content
                    )
                    logger.info(
                        "planner_objectives_updated",
                        session_id=state.session.session_id,
                    )
            except Exception as e:
                logger.warning("planner_objectives_update_failed", error=str(e))

        inputs = {
            "prompt": state.session.prompt,
            "history": str(state.messages or []),
            "journal": state.journal,
            "review_feedback": (
                state.review_feedback
                if state.session.status == SessionStatus.REJECTED
                else "No feedback yet."
            ),
        }

        if settings.is_integration_test:
            validate_files = [
                PLAN_FILE,
                "todo.md",
                "benchmark_definition.yaml",
                "benchmark_assembly_definition.yaml",
            ]
            prediction, _, journal_entry = await self._run_program(
                dspy.ReAct,
                BenchmarkPlannerSignature,
                state,
                inputs,
                get_benchmark_planner_tools,
                validate_files,
                AgentName.BENCHMARK_PLANNER,
            )
        else:
            prediction, _, journal_entry = await self._run_native_planner(
                state=state,
                inputs=inputs,
            )

        if not prediction:
            state.plan = None
            state.session.validation_logs.append(
                "benchmark_planner failed: no valid planner output produced"
            )
            state.journal += f"\n[Planner] Failed: {journal_entry}"
            return state

        submission, submit_err = await self._get_latest_submit_plan_result(
            AgentName.BENCHMARK_PLANNER
        )
        submit_tool_name = self._planner_submission_tool_name(
            AgentName.BENCHMARK_PLANNER
        )
        if submission is None or not submission.ok or submission.status != "submitted":
            submit_errors = (
                [submit_err]
                if submit_err
                else (
                    submission.errors if submission else [f"{submit_tool_name} failed"]
                )
            )
            error_text = (
                "; ".join([e for e in submit_errors if e])
                or f"{submit_tool_name} failed"
            )
            state.plan = None
            state.session.validation_logs.append(
                f"benchmark_planner {submit_tool_name} validation failed: {error_text}"
            )
            state.journal += (
                f"\n[Planner] {submit_tool_name} validation failed: "
                + error_text
                + journal_entry
            )
            return state

        raw_plan = getattr(prediction, "plan", None)
        normalized_plan: RandomizationStrategy | None = None

        if isinstance(raw_plan, RandomizationStrategy):
            normalized_plan = raw_plan
        elif isinstance(raw_plan, dict):
            with suppress(Exception):
                normalized_plan = RandomizationStrategy.model_validate(raw_plan)
        elif isinstance(raw_plan, str):
            raw_plan_text = raw_plan.strip()
            if raw_plan_text:
                with suppress(Exception):
                    normalized_plan = RandomizationStrategy.model_validate_json(
                        raw_plan_text
                    )
                if normalized_plan is None:
                    with suppress(Exception):
                        normalized_plan = RandomizationStrategy.model_validate(
                            yaml.safe_load(raw_plan_text)
                        )

        if normalized_plan is None:
            state.plan = None
            state.session.validation_logs.append(
                "benchmark_planner failed: plan output is missing or invalid. "
                f"Retry planner and call {submit_tool_name}() with schema-valid artifacts."
            )
            state.journal += (
                "\n[Planner] Invalid or missing structured plan output. "
                "Retry required." + journal_entry
            )
            return state

        state.plan = normalized_plan
        state.journal += (
            f"\n[Planner] {getattr(prediction, 'reasoning', '')}\n{journal_entry}"
        )
        state.messages.append(
            HumanMessage(content=f"Generated plan: {state.plan.theme}")
        )
        return state

    def _resolve_native_dspy_model(
        self, *, prefer_multimodal: bool = False
    ) -> LiteLLMRequestConfig:
        return super()._resolve_native_dspy_model(prefer_multimodal=prefer_multimodal)

    @staticmethod
    def _native_schema_type(annotation: Any) -> str:
        if annotation is bool:
            return "boolean"
        if annotation is int:
            return "integer"
        if annotation is float:
            return "number"
        if annotation in {dict, dict[str, Any]}:
            return "object"
        if annotation in {list, list[str], list[Any]}:
            return "array"
        return "string"

    def _build_native_tool_schemas(
        self,
        tool_fns: dict[str, Any],
        *,
        extra_schemas: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        schemas: list[dict[str, Any]] = []
        for tool_name, tool_fn in tool_fns.items():
            signature = inspect.signature(tool_fn)
            properties: dict[str, Any] = {}
            required: list[str] = []

            for param_name, param in signature.parameters.items():
                if param.kind not in (
                    inspect.Parameter.POSITIONAL_OR_KEYWORD,
                    inspect.Parameter.KEYWORD_ONLY,
                ):
                    continue
                annotation = (
                    param.annotation
                    if param.annotation is not inspect.Signature.empty
                    else str
                )
                properties[param_name] = {
                    "type": self._native_schema_type(annotation),
                }
                if param.default is inspect.Signature.empty:
                    required.append(param_name)
                else:
                    properties[param_name]["default"] = param.default

            schemas.append(
                {
                    "type": "function",
                    "function": {
                        "name": tool_name,
                        "description": inspect.getdoc(tool_fn) or "",
                        "parameters": {
                            "type": "object",
                            "properties": properties,
                            "required": required,
                            "additionalProperties": False,
                        },
                    },
                }
            )

        if extra_schemas:
            schemas.extend(extra_schemas)

        return schemas

    def _build_native_planner_messages(
        self, inputs: dict[str, Any]
    ) -> list[dict[str, Any]]:
        system_prompt = (
            self.ctx.pm.render(
                AgentName.BENCHMARK_PLANNER,
                backend_family="api_based",
            ).strip()
            + "\n\n"
            + self._get_runtime_prompt(
                "benchmark_generator.runtime.native_planner_contract"
            )
        )
        user_prompt = "Benchmark planner inputs:\n" + json.dumps(
            inputs, indent=2, ensure_ascii=True, default=str
        )
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

    @staticmethod
    def _coerce_message_text(content: Any) -> str:
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            text_chunks: list[str] = []
            for block in content:
                if isinstance(block, str):
                    if block.strip():
                        text_chunks.append(block.strip())
                    continue
                if isinstance(block, dict):
                    text_value = block.get("text")
                    if isinstance(text_value, str) and text_value.strip():
                        text_chunks.append(text_value.strip())
                        continue
                    nested_text = block.get("content")
                    if isinstance(nested_text, str) and nested_text.strip():
                        text_chunks.append(nested_text.strip())
                        continue
                text_value = getattr(block, "text", None)
                if isinstance(text_value, str) and text_value.strip():
                    text_chunks.append(text_value.strip())
                    continue
                nested_text = getattr(block, "content", None)
                if isinstance(nested_text, str) and nested_text.strip():
                    text_chunks.append(nested_text.strip())
            if text_chunks:
                return "\n".join(text_chunks)
        if content is None:
            return ""
        return str(content).strip()

    def _derive_randomization_strategy(
        self,
        *,
        task_prompt: str,
        artifacts: dict[str, Any],
        reasoning: str,
    ) -> dict[str, Any]:
        objectives_raw = artifacts.get("benchmark_definition.yaml", "")
        objectives_data = {}
        with suppress(Exception):
            parsed = yaml.safe_load(objectives_raw)
            if isinstance(parsed, dict):
                objectives_data = parsed

        plan_markdown = str(artifacts.get(PLAN_FILE, "") or "")
        learning_objective = _extract_markdown_section(
            plan_markdown, "## 1. Learning Objective"
        )
        static_geometry = _extract_markdown_section(
            plan_markdown, "## 2. Static Geometry"
        )
        randomization = _extract_markdown_section(plan_markdown, "## 6. Randomization")

        theme = (
            (learning_objective.splitlines()[0].strip() if learning_objective else "")
            or task_prompt.strip()
            or "Benchmark planning task"
        )

        environment_perturbations: dict[str, Any] = {}
        if randomization:
            environment_perturbations["randomization_plan"] = randomization
        if static_geometry:
            environment_perturbations["static_geometry"] = static_geometry

        payload = objectives_data.get("payload")
        target_object_properties = payload if isinstance(payload, dict) else {}

        return RandomizationStrategy(
            theme=theme[:200],
            target_object_properties=target_object_properties,
            environment_perturbations=environment_perturbations,
            difficulty_score=0.5,
            reasoning=reasoning.strip() or None,
        ).model_dump(mode="json")

    async def _normalize_benchmark_definition_yaml_artifact(self) -> bool:
        if not await self.ctx.fs.exists(BENCHMARK_DEFINITION_FILE):
            return False

        raw_content = await self.ctx.fs.read_file(BENCHMARK_DEFINITION_FILE)
        if not raw_content.strip():
            return False

        data = yaml.safe_load(raw_content)
        if not isinstance(data, dict):
            return False

        changed = False
        normalized_totals: dict[str, float] = {}
        removed_keys: list[str] = []

        payload = data.get("payload")
        if isinstance(payload, dict):
            static_randomization = payload.get("static_randomization")
            if isinstance(static_randomization, dict):
                nested_start_position = static_randomization.pop("start_position", None)
                if (
                    nested_start_position is not None
                    and "start_position" not in payload
                ):
                    payload["start_position"] = nested_start_position
                    changed = True
                elif nested_start_position is not None:
                    static_randomization["start_position"] = nested_start_position

        assembly_totals = data.get("assembly_totals")
        if isinstance(assembly_totals, dict):
            for key, value in assembly_totals.items():
                if isinstance(value, bool):
                    removed_keys.append(key)
                    changed = True
                    continue
                if isinstance(value, (int, float)):
                    normalized_totals[key] = float(value)
                    continue
                if isinstance(value, str):
                    with suppress(ValueError):
                        normalized_totals[key] = float(value)
                        changed = True
                        continue
                removed_keys.append(key)
                changed = True

            if normalized_totals:
                if normalized_totals != assembly_totals:
                    changed = True
                data["assembly_totals"] = normalized_totals
            elif assembly_totals:
                data.pop("assembly_totals", None)
                changed = True

        if not changed:
            return False

        await self.ctx.fs.write_file(
            BENCHMARK_DEFINITION_FILE,
            yaml.safe_dump(data, sort_keys=False),
            overwrite=True,
        )
        logger.info(
            "benchmark_planner_normalized_benchmark_definition_yaml",
            session_id=self.ctx.session_id,
            removed_keys=removed_keys,
            kept_keys=sorted(normalized_totals.keys()),
            promoted_start_position=bool(
                isinstance(data.get("payload"), dict)
                and data["payload"].get("start_position") is not None
            ),
        )
        return True

    async def _normalize_todo_markdown_artifact(self) -> bool:
        todo_path = "todo.md"
        if not await self.ctx.fs.exists(todo_path):
            return False

        raw_content = await self.ctx.fs.read_file(todo_path)
        if not raw_content.strip():
            return False

        lines = raw_content.splitlines()
        normalized_lines: list[str] = []
        changed = False

        for line in lines:
            stripped = line.lstrip()
            indent = line[: len(line) - len(stripped)]
            if stripped.startswith("- ") and not stripped.startswith(
                ("- [ ] ", "- [x] ", "- [-] ")
            ):
                normalized_lines.append(f"{indent}- [ ] {stripped[2:]}")
                changed = True
            else:
                normalized_lines.append(line)

        if not changed:
            return False

        normalized_content = "\n".join(normalized_lines)
        if raw_content.endswith("\n"):
            normalized_content += "\n"

        await self.ctx.fs.write_file(
            todo_path,
            normalized_content,
            overwrite=True,
        )
        logger.info(
            "benchmark_planner_normalized_todo_md",
            session_id=self.ctx.session_id,
        )
        return True

    async def _run_native_planner(
        self,
        *,
        state: BenchmarkGeneratorState,
        inputs: dict[str, Any],
    ) -> tuple[NativePlannerPrediction | None, dict[str, Any], str]:
        from worker_heavy.utils.file_validation import validate_node_output

        max_retries = max(1, int(settings.dspy_program_max_retries))
        validate_files = [
            PLAN_FILE,
            "todo.md",
            "benchmark_definition.yaml",
            "benchmark_assembly_definition.yaml",
        ]
        episode_id = getattr(state, "episode_id", None) or self.ctx.episode_id
        db_callback = None
        if episode_id and str(episode_id).strip():
            db_callback = self.ctx.get_database_recorder(str(episode_id))

        tool_fns = self._get_tool_functions(
            get_benchmark_planner_tools,
            db_callback=db_callback,
            node_name=AgentName.BENCHMARK_PLANNER,
        )
        tool_schemas = self._build_native_tool_schemas(tool_fns)
        journal_entry = ""
        artifacts: dict[str, Any] = {}

        for retry_count in range(max_retries):
            try:
                planner_execution_policy = self.ctx.fs.policy.get_execution_policy(
                    AgentName.BENCHMARK_PLANNER
                )
                attempt_budget_seconds = max(
                    30.0,
                    (
                        float(planner_execution_policy.timeout_seconds)
                        / float(max_retries)
                    )
                    - 5.0,
                )
                attempt_started_at = time.monotonic()
                trace_watermark = (
                    await self._get_latest_trace_id(db_callback) if db_callback else 0
                )
                if db_callback:
                    await db_callback.record_node_start(
                        AgentName.BENCHMARK_PLANNER,
                        input_data=str(inputs.get("prompt", "")),
                    )

                reasoning_chunks: list[str] = []
                messages = self._build_native_planner_messages(inputs)
                request_config = self._resolve_native_dspy_model()
                submit_tool_name = self._planner_submission_tool_name(
                    AgentName.BENCHMARK_PLANNER
                )

                submitted = False
                last_submit_error_text: str | None = None
                cots_search_budget = 2
                cots_search_calls = 0
                no_tool_call_streak = 0
                completion_timeout_streak = 0
                for step_idx in range(
                    planner_execution_policy.native_tool_loop_max_iters
                ):
                    elapsed_seconds = time.monotonic() - attempt_started_at
                    if elapsed_seconds >= attempt_budget_seconds:
                        raise RuntimeError(
                            "Native benchmark planner attempt budget exceeded "
                            f"({elapsed_seconds:.1f}s >= {attempt_budget_seconds:.1f}s)."
                        )

                    try:
                        native_lm = build_dspy_lm(
                            request_config.model,
                            session_id=self.ctx.session_id,
                            agent_role=AgentName.BENCHMARK_PLANNER.value,
                        ).copy(
                            timeout=settings.native_tool_completion_timeout_seconds,
                            # Keep the tool-loop request below the current OpenRouter credit ceiling.
                            max_tokens=min(
                                settings.llm_max_tokens,
                                _NATIVE_TOOL_COMPLETION_MAX_TOKENS,
                            ),
                        )
                        response = await asyncio.to_thread(
                            native_lm,
                            messages=messages,
                            tools=tool_schemas,
                            tool_choice="auto",
                        )
                    except Exception as completion_err:
                        error_text = (
                            str(completion_err).strip()
                            or "native completion call failed"
                        )
                        logger.warning(
                            "benchmark_native_completion_failed",
                            session_id=self.ctx.session_id,
                            error=error_text,
                            step_index=step_idx,
                            retry_count=retry_count + 1,
                        )
                        completion_timeout_streak += 1
                        messages.append(
                            {
                                "role": "system",
                                "content": self._get_runtime_prompt(
                                    "benchmark_generator.runtime.no_tool_call_nudge"
                                ),
                            }
                        )
                        if completion_timeout_streak >= 3:
                            raise RuntimeError(
                                "Native benchmark planner completion timed out "
                                "repeatedly; aborting planner attempt."
                            ) from completion_err
                        continue

                    completion_timeout_streak = 0
                    message = response.choices[0].message
                    assistant_text, tool_calls = self._extract_native_tool_calls(
                        message,
                        model_name=request_config.model,
                    )
                    if assistant_text:
                        reasoning_chunks.append(assistant_text)
                        if db_callback:
                            await db_callback.record_reasoning_text(
                                node_name=str(AgentName.BENCHMARK_PLANNER),
                                reasoning_text=assistant_text,
                                step_index=step_idx,
                                source="native_tool_loop",
                            )

                    if not tool_calls:
                        no_tool_call_streak += 1
                        messages.append(
                            {
                                "role": "assistant",
                                "content": assistant_text
                                or "No tool call emitted on this turn.",
                            }
                        )
                        messages.append(
                            {
                                "role": "system",
                                "content": self._get_runtime_prompt(
                                    "benchmark_generator.runtime.no_tool_call_nudge"
                                    if no_tool_call_streak > 2
                                    else "benchmark_generator.runtime.continue_from_workspace"
                                ),
                            }
                        )
                        if no_tool_call_streak >= 6:
                            raise ValueError(
                                "Native benchmark planner returned no tool calls "
                                f"repeatedly before {submit_tool_name}()."
                            )
                        continue

                    no_tool_call_streak = 0

                    messages.append(
                        self._assistant_message_with_tool_calls(
                            message,
                            model_name=request_config.model,
                            assistant_text=assistant_text,
                            tool_calls_payload=tool_calls,
                        )
                    )

                    for tool_call in tool_calls:
                        function = tool_call.get("function", {})
                        tool_name = function.get("name")
                        if not tool_name or tool_name not in tool_fns:
                            raise ValueError(
                                f"Native benchmark planner requested unknown tool: {tool_name}"
                            )

                        raw_arguments = (
                            tool_call.get("function", {}).get("arguments", "{}") or "{}"
                        )
                        arguments, argument_error = self._parse_native_tool_arguments(
                            str(tool_name), raw_arguments
                        )
                        if argument_error:
                            logger.warning(
                                "benchmark_native_tool_call_payload_invalid",
                                session_id=self.ctx.session_id,
                                tool_name=tool_name,
                                error=argument_error,
                            )
                            messages.append(
                                self._tool_response_message(
                                    tool_call_id=tool_call.get("id", ""),
                                    tool_name=str(tool_name),
                                    content=argument_error,
                                )
                            )
                            messages.append(
                                {
                                    "role": "system",
                                    "content": self._get_runtime_prompt(
                                        "benchmark_generator.runtime.invalid_tool_arguments_recover",
                                        tool_name=str(tool_name),
                                    ),
                                }
                            )
                            continue

                        if (
                            tool_name == "invoke_cots_search_subagent"
                            and cots_search_calls >= cots_search_budget
                        ):
                            budget_msg = self._get_runtime_prompt(
                                "benchmark_generator.runtime.cots_search_budget_exhausted",
                                max_calls=cots_search_budget,
                            )
                            messages.append(
                                self._tool_response_message(
                                    tool_call_id=tool_call.get("id", ""),
                                    tool_name=str(tool_name),
                                    content=budget_msg,
                                )
                            )
                            messages.append({"role": "system", "content": budget_msg})
                            continue

                        if tool_name == submit_tool_name:
                            await self._normalize_benchmark_definition_yaml_artifact()
                            await self._normalize_todo_markdown_artifact()
                        try:
                            result = await asyncio.to_thread(
                                tool_fns[tool_name], **arguments
                            )
                        except Exception as err:
                            error_text = str(err).strip() or f"{tool_name} failed"
                            if _SYSTEM_TOOL_RETRY_EXHAUSTED_MARKER in error_text:
                                raise RuntimeError(error_text) from err
                            logger.warning(
                                "benchmark_native_tool_call_failed",
                                session_id=self.ctx.session_id,
                                tool_name=tool_name,
                                error=error_text,
                            )
                            messages.append(
                                self._tool_response_message(
                                    tool_call_id=tool_call.get("id", ""),
                                    tool_name=str(tool_name),
                                    content=f"{tool_name} failed: {error_text}",
                                )
                            )
                            messages.append(
                                {
                                    "role": "system",
                                    "content": self._get_runtime_prompt(
                                        "benchmark_generator.runtime.tool_call_failed_recover",
                                        tool_name=str(tool_name),
                                    ),
                                }
                            )
                            continue
                        result_text = self._serialize_tool_observation(result)

                        messages.append(
                            self._tool_response_message(
                                tool_call_id=tool_call.get("id", ""),
                                tool_name=str(tool_name),
                                content=result_text,
                            )
                        )

                        if tool_name == "invoke_cots_search_subagent":
                            cots_search_calls += 1

                        if tool_name == submit_tool_name:
                            submission = result
                            if isinstance(submission, str):
                                with suppress(Exception):
                                    submission = json.loads(submission)
                            if (
                                isinstance(submission, dict)
                                and submission.get("ok") is True
                                and submission.get("status") == "submitted"
                            ):
                                submitted = True
                                messages.append(
                                    {
                                        "role": "system",
                                        "content": self._get_runtime_prompt(
                                            "benchmark_generator.runtime.submit_succeeded_finish_now"
                                        ),
                                    }
                                )
                            else:
                                last_submit_error_text = (
                                    self._submit_plan_error_message(submission)
                                    or "unknown validation error"
                                )
                                if (
                                    "CONTRADICTORY_CONSTRAINTS"
                                    in last_submit_error_text
                                ):
                                    messages.append(
                                        {
                                            "role": "system",
                                            "content": (
                                                f"{submit_tool_name}() rejected terminal "
                                                "contradictory benchmark motion: "
                                                f"{last_submit_error_text}. Stop "
                                                f"retrying {submit_tool_name}() and let "
                                                "handoff validation fail closed."
                                            ),
                                        }
                                    )
                                    break
                                messages.append(
                                    {
                                        "role": "system",
                                        "content": self._get_runtime_prompt(
                                            "benchmark_generator.runtime.submit_rejected_fix_and_retry",
                                            error_text=last_submit_error_text,
                                        ),
                                    }
                                )

                    if submitted:
                        break

                await self._normalize_benchmark_definition_yaml_artifact()
                await self._normalize_todo_markdown_artifact()

                if not submitted:
                    submit_tool = tool_fns.get(submit_tool_name)
                    if submit_tool is not None:
                        submission = await asyncio.to_thread(submit_tool)
                        if isinstance(submission, str):
                            with suppress(Exception):
                                submission = json.loads(submission)
                        if (
                            isinstance(submission, dict)
                            and submission.get("ok") is True
                            and submission.get("status") == "submitted"
                        ):
                            submitted = True
                        else:
                            last_submit_error_text = (
                                self._submit_plan_error_message(submission)
                                or last_submit_error_text
                            )
                            if "CONTRADICTORY_CONSTRAINTS" in last_submit_error_text:
                                break

                if not submitted:
                    submit_error_suffix = (
                        f" Last {submit_tool_name} errors: {last_submit_error_text}"
                        if last_submit_error_text
                        else ""
                    )
                    if last_submit_error_text and "CONTRADICTORY_CONSTRAINTS" in (
                        last_submit_error_text or ""
                    ):
                        return None, artifacts, journal_entry
                    raise ValueError(
                        "Native benchmark planner exhausted tool loop without "
                        f"successful {submit_tool_name}().{submit_error_suffix}"
                    )

                results = await asyncio.gather(
                    *[self.ctx.fs.read_file(f) for f in validate_files],
                    return_exceptions=True,
                )
                artifacts = {
                    f: res
                    for f, res in zip(validate_files, results, strict=False)
                    if not isinstance(res, Exception)
                }

                is_valid, validation_errors = validate_node_output(
                    AgentName.BENCHMARK_PLANNER, artifacts
                )
                if not is_valid:
                    raise ValueError(
                        "benchmark_planner validation failed: "
                        + "; ".join(validation_errors)
                    )

                if settings.require_reasoning_traces and db_callback:
                    reasoning_count = await self._count_reasoning_traces_since(
                        db_callback,
                        node_type=AgentName.BENCHMARK_PLANNER,
                        min_trace_id=trace_watermark,
                    )
                    if reasoning_count == 0:
                        raise ValueError(
                            "benchmark_planner produced no reasoning traces in native tool loop."
                        )

                prediction = NativePlannerPrediction(
                    reasoning="\n".join(chunk for chunk in reasoning_chunks if chunk),
                    plan=self._derive_randomization_strategy(
                        task_prompt=str(inputs.get("prompt", "")),
                        artifacts=artifacts,
                        reasoning="\n".join(
                            chunk for chunk in reasoning_chunks if chunk
                        ),
                    ),
                )

                if db_callback:
                    await db_callback.record_node_end(
                        AgentName.BENCHMARK_PLANNER,
                        output_data=str(prediction),
                        output_obj=prediction,
                    )
                return prediction, artifacts, journal_entry
            except Exception as err:
                logger.error(
                    "benchmark_planner_native_failed",
                    session_id=self.ctx.session_id,
                    error=str(err),
                    retry_count=retry_count + 1,
                    max_retries=max_retries,
                )
                if _is_transient_provider_rate_error(err):
                    raise RuntimeError(str(err)) from err
                journal_entry += f"\n[System Error] {err}"
                if retry_count + 1 >= max_retries:
                    break
                await asyncio.sleep(1)

        journal_entry += "\nMax retries reached."
        return None, artifacts, journal_entry


@type_check
async def planner_node(state: BenchmarkGeneratorState) -> BenchmarkGeneratorState:
    from controller.config.settings import settings as global_settings

    worker_light_url = global_settings.worker_light_url
    ctx = SharedNodeContext.create(
        worker_light_url=worker_light_url,
        session_id=_benchmark_worker_session_id(state),
        episode_id=state.episode_id,
        agent_role=AgentName.BENCHMARK_PLANNER,
    )
    node = BenchmarkPlannerNode(context=ctx)
    return await node(state)


class BenchmarkPlanReviewerSignature(dspy.Signature):
    """DSPy signature for the benchmark plan reviewer."""

    prompt = dspy.InputField()
    plan_md = dspy.InputField()
    todo_md = dspy.InputField()
    benchmark_definition_yaml = dspy.InputField()
    benchmark_assembly_definition_yaml = dspy.InputField()
    solvability_evidence = dspy.InputField()
    journal = dspy.InputField()
    review_feedback = dspy.InputField()
    review: ReviewResult = dspy.OutputField()


@type_check
class BenchmarkPlanReviewerNode(BaseNode):
    """Review benchmark planner artifacts before execution begins."""

    @staticmethod
    def _normalize_render_path(path: str) -> str:
        normalized = Path(path).as_posix()
        if not normalized.startswith("/"):
            normalized = f"/{normalized}"
        return normalized

    def _normalize_render_paths(self, render_paths: list[str]) -> list[str]:
        return sorted(
            dict.fromkeys(
                self._normalize_render_path(path)
                for path in render_paths
                if path and path.strip()
            )
        )

    def _augment_review_checklist(
        self,
        review: ReviewResult,
        evidence: BenchmarkPlanReviewerEvidence,
        *,
        inspected_render_paths: list[str],
    ) -> ReviewResult:
        policy = self._get_visual_inspection_policy(AgentName.BENCHMARK_PLAN_REVIEWER)
        checklist = dict(review.checklist or {})
        normalized_render_paths = self._normalize_render_paths(evidence.render_paths)
        normalized_inspected_render_paths = self._normalize_render_paths(
            inspected_render_paths
        )
        checklist.update(
            {
                "latest_revision_verified": bool(evidence.latest_revision_verified),
                "review_manifest_revision": evidence.review_manifest_revision or "",
                "review_manifest_script_sha256": (
                    evidence.review_manifest_script_sha256 or ""
                ),
                "benchmark_attachment_policy_count": float(
                    len(evidence.attachment_policy_summary)
                ),
                "benchmark_attachment_policy_summary": json.dumps(
                    [
                        summary.model_dump(mode="json")
                        for summary in evidence.attachment_policy_summary
                    ],
                    sort_keys=True,
                ),
                "render_count": float(len(normalized_render_paths)),
                "render_paths": ", ".join(normalized_render_paths),
                "inspected_render_count": float(len(normalized_inspected_render_paths)),
                "visual_inspection_min_images": float(policy.min_images),
                "visual_inspection_satisfied": bool(
                    len(normalized_inspected_render_paths) >= policy.min_images
                ),
                "deterministic_error_count": float(len(evidence.deterministic_errors)),
                "deterministic_refusal_reason": (
                    evidence.refusal_reason.value
                    if evidence.refusal_reason is not None
                    else "none"
                ),
            }
        )
        if evidence.solvability_summary:
            checklist.setdefault("solvability_summary", evidence.solvability_summary)
        return review.model_copy(update={"checklist": checklist})

    async def _enforce_render_inspection_gate(
        self,
        review: ReviewResult,
        evidence: BenchmarkPlanReviewerEvidence,
    ) -> ReviewResult:
        policy = self._get_visual_inspection_policy(AgentName.BENCHMARK_PLAN_REVIEWER)
        if not policy.required:
            return review

        render_paths = self._normalize_render_paths(evidence.render_paths)
        if not render_paths:
            fixes = list(review.required_fixes or [])
            fixes.append(
                "Generate current-revision render image(s) at or above 640x480 "
                "before requesting benchmark plan approval."
            )
            checklist = dict(review.checklist or {})
            checklist.update(
                {
                    "latest_revision_verified": bool(evidence.latest_revision_verified),
                    "review_manifest_revision": evidence.review_manifest_revision or "",
                    "benchmark_attachment_policy_count": float(
                        len(evidence.attachment_policy_summary)
                    ),
                    "benchmark_attachment_policy_summary": json.dumps(
                        [
                            summary.model_dump(mode="json")
                            for summary in evidence.attachment_policy_summary
                        ],
                        sort_keys=True,
                    ),
                    "render_count": 0.0,
                    "render_paths": "",
                    "inspected_render_count": 0.0,
                    "visual_inspection_min_images": float(policy.min_images),
                    "visual_inspection_satisfied": False,
                    "deterministic_error_count": float(
                        len(evidence.deterministic_errors)
                    ),
                    "deterministic_refusal_reason": (
                        evidence.refusal_reason.value
                        if evidence.refusal_reason is not None
                        else "none"
                    ),
                }
            )
            if evidence.solvability_summary:
                checklist.setdefault(
                    "solvability_summary", evidence.solvability_summary
                )
            return review.model_copy(
                update={
                    "decision": ReviewDecision.REJECT_PLAN,
                    "reason": (
                        "Approval blocked: current-revision benchmark render "
                        "media is missing."
                    ),
                    "required_fixes": fixes,
                    "checklist": checklist,
                }
            )

        inspected_render_paths = [
            path for path in render_paths if path in set(self._inspected_media_paths)
        ]
        if len(set(inspected_render_paths)) >= policy.min_images:
            return review

        fixes = list(review.required_fixes or [])
        render_examples = ", ".join(render_paths[: min(3, len(render_paths))])
        fixes.append(
            "Inspect at least "
            f"{policy.min_images} current-revision render image(s) via "
            f"inspect_media(path) before deciding. Latest revision render paths: "
            f"{render_examples}."
        )
        checklist = dict(review.checklist or {})
        checklist.update(
            {
                "latest_revision_verified": bool(evidence.latest_revision_verified),
                "review_manifest_revision": evidence.review_manifest_revision or "",
                "benchmark_attachment_policy_count": float(
                    len(evidence.attachment_policy_summary)
                ),
                "benchmark_attachment_policy_summary": json.dumps(
                    [
                        summary.model_dump(mode="json")
                        for summary in evidence.attachment_policy_summary
                    ],
                    sort_keys=True,
                ),
                "render_count": float(len(render_paths)),
                "render_paths": ", ".join(render_paths),
                "inspected_render_count": float(len(inspected_render_paths)),
                "visual_inspection_min_images": float(policy.min_images),
                "visual_inspection_satisfied": False,
                "deterministic_error_count": float(len(evidence.deterministic_errors)),
                "deterministic_refusal_reason": (
                    evidence.refusal_reason.value
                    if evidence.refusal_reason is not None
                    else "none"
                ),
            }
        )
        if evidence.solvability_summary:
            checklist.setdefault("solvability_summary", evidence.solvability_summary)
        return review.model_copy(
            update={
                "decision": ReviewDecision.REJECT_PLAN,
                "reason": (
                    "Plan review blocked: current-revision render evidence exists, "
                    "but the reviewer did not inspect it with inspect_media(path) "
                    "during this review attempt."
                ),
                "required_fixes": fixes,
                "checklist": checklist,
            }
        )

    async def __call__(self, state: BenchmarkGeneratorState) -> BenchmarkGeneratorState:
        plan_md = f"# No {PLAN_FILE} found."
        todo_md = "# No todo.md found."
        benchmark_definition_yaml = "# No benchmark_definition.yaml found."
        benchmark_assembly_definition_yaml = (
            "# No benchmark_assembly_definition.yaml found."
        )

        with suppress(Exception):
            plan_md = (
                await self.ctx.worker_client.read_file_optional(PLAN_FILE) or plan_md
            )
        with suppress(Exception):
            todo_md = (
                await self.ctx.worker_client.read_file_optional("todo.md") or todo_md
            )
        with suppress(Exception):
            benchmark_definition_yaml = (
                await self.ctx.worker_client.read_file_optional(
                    BENCHMARK_DEFINITION_FILE
                )
                or benchmark_definition_yaml
            )
        with suppress(Exception):
            benchmark_assembly_definition_yaml = (
                await self.ctx.worker_client.read_file_optional(
                    "benchmark_assembly_definition.yaml"
                )
                or benchmark_assembly_definition_yaml
            )

        evidence, evidence_error = await collect_plan_reviewer_handover_evidence(
            self.ctx.worker_client,
            manifest_path=".manifests/benchmark_plan_review_manifest.json",
            expected_stage=AgentName.BENCHMARK_PLAN_REVIEWER,
            episode_id=state.episode_id,
        )
        if evidence_error is not None:
            state.review_decision = None
            state.review_feedback = (
                "Plan reviewer output invalid: failed to collect latest-revision "
                f"solvability evidence: {evidence_error}"
            )
            state.journal += f"\n[Plan Reviewer] Failed: {evidence_error}"
            return state
        assert evidence is not None
        solvability_evidence = evidence

        inputs = {
            "prompt": state.session.prompt,
            "plan_md": plan_md,
            "todo_md": todo_md,
            "benchmark_definition_yaml": benchmark_definition_yaml,
            "benchmark_assembly_definition_yaml": benchmark_assembly_definition_yaml,
            "solvability_evidence": solvability_evidence.to_prompt_text(),
            "journal": state.journal,
            "review_feedback": state.review_feedback or "No feedback provided.",
        }

        def get_plan_reviewer_tools(fs, session_id):
            tools = get_benchmark_tools(fs, session_id)
            allowed_tools = {
                "list_files",
                "read_file",
                "inspect_media",
                "grep",
                "execute_command",
                "inspect_topology",
            }
            narrowed_tools = [
                tool
                for tool in tools
                if getattr(tool, "name", getattr(tool, "__name__", None))
                in allowed_tools
            ]
            return filter_tools_for_agent(fs, narrowed_tools)

        prediction, _, journal_entry = await self._run_program(
            dspy.ReAct,
            BenchmarkPlanReviewerSignature,
            state,
            inputs,
            get_plan_reviewer_tools,
            [
                PLAN_FILE,
                "todo.md",
                "benchmark_definition.yaml",
                "benchmark_assembly_definition.yaml",
            ],
            AgentName.BENCHMARK_PLAN_REVIEWER,
        )

        if not prediction:
            state.review_decision = None
            state.review_feedback = (
                "Plan reviewer output invalid: failed to produce a structured "
                "review decision."
            )
            state.journal += f"\n[Plan Reviewer] Failed: {journal_entry}"
            return state

        try:
            review = ReviewResult.model_validate(prediction.review)
            normalized_inspected_media_paths = {
                self._normalize_inspected_media_path(path)
                for path in self._inspected_media_paths
            }
            inspected_render_paths = [
                path
                for path in solvability_evidence.render_paths
                if self._normalize_render_path(path) in normalized_inspected_media_paths
            ]
            review = self._augment_review_checklist(
                review,
                solvability_evidence,
                inspected_render_paths=inspected_render_paths,
            )
            review = await self._enforce_render_inspection_gate(
                review,
                solvability_evidence,
            )
            (
                review_decision_path,
                review_comments_path,
            ) = await self._persist_review_result(review, "benchmark-plan-review")
        except Exception as exc:
            state.review_decision = None
            state.review_feedback = (
                "Plan reviewer output invalid: failed to persist structured "
                f"review artifacts: {exc}"
            )
            state.journal += (
                f"\n[Plan Reviewer] Review persistence failed: {exc}\n{journal_entry}"
            )
            return state

        state.review_decision = review.decision
        state.review_feedback = f"{review.decision.value}: {review.reason}"
        if review.required_fixes:
            state.review_feedback += "\nFixes: " + ", ".join(review.required_fixes)
        state.journal += (
            "\n[Plan Reviewer Evidence] "
            f"revision={solvability_evidence.review_manifest_revision or 'unknown'} "
            f"renders={solvability_evidence.render_count} "
            f"deterministic_errors={len(solvability_evidence.deterministic_errors)}"
        )
        state.journal += (
            f"\n[Plan Reviewer] {state.review_feedback}\n"
            f"Decision file: {review_decision_path}\n"
            f"Comments file: {review_comments_path}\n"
            f"{journal_entry}"
        )
        review_id = uuid.uuid4().hex
        await record_worker_events(
            episode_id=state.episode_id,
            events=[
                ReviewDecisionEvent(
                    decision=review.decision,
                    reason=state.review_feedback,
                    review_id=review_id,
                    evidence_stats={
                        "is_plan_review": True,
                        "num_renders": solvability_evidence.render_count,
                        "review_decision_path": review_decision_path,
                        "review_comments_path": review_comments_path,
                    },
                    checklist=review.checklist,
                )
            ],
        )
        state.messages.append(
            AIMessage(content=f"Plan Review decision: {review.decision.value}")
        )
        return state


@type_check
async def plan_reviewer_node(state: BenchmarkGeneratorState) -> BenchmarkGeneratorState:
    from controller.config.settings import settings as global_settings

    worker_light_url = global_settings.worker_light_url
    ctx = SharedNodeContext.create(
        worker_light_url=worker_light_url,
        session_id=_benchmark_worker_session_id(state),
        episode_id=state.episode_id,
        agent_role=AgentName.BENCHMARK_PLAN_REVIEWER,
    )
    node = BenchmarkPlanReviewerNode(context=ctx)
    return await node(state)


class BenchmarkCoderSignature(dspy.Signature):
    """DSPy signature for the benchmark coder."""

    prompt = dspy.InputField()
    plan = dspy.InputField()
    benchmark_definition_yaml = dspy.InputField()
    review_feedback = dspy.InputField()
    validation_logs = dspy.InputField()
    journal = dspy.OutputField(desc="A summary of what was done")


@type_check
class BenchmarkCoderNode(BaseNode):
    """Refactored Benchmark Coder using BaseNode."""

    async def _download_render_data(
        self, *, render_paths: list[str], session_id: str
    ) -> list[bytes]:
        async def _download(url_path: str) -> bytes | None:
            from controller.config.settings import settings as global_settings

            worker_light_url = global_settings.worker_light_url
            url = f"{worker_light_url}/assets/{url_path.lstrip('/')}"
            try:
                async with httpx.AsyncClient() as http_client:
                    response = await http_client.get(
                        url,
                        headers={
                            "X-Session-ID": session_id,
                            "X-Agent-Role": AgentName.BENCHMARK_CODER.value,
                            "X-Stage": AgentName.BENCHMARK_CODER.value,
                        },
                    )
                    return response.content if response.status_code == 200 else None
            except Exception:
                return None

        results = await asyncio.gather(*[_download(path) for path in render_paths])
        return [result for result in results if result is not None]

    async def _load_fresh_validation_record(
        self, *, script_content: str
    ) -> ValidationResultRecord | None:
        try:
            raw_record = await self.ctx.worker_client.read_file_optional(
                "validation_results.json"
            )
            if raw_record is None:
                return None
            record = ValidationResultRecord.model_validate_json(raw_record)
        except Exception as exc:
            logger.warning("persisted_validation_record_invalid", error=str(exc))
            return None

        script_sha = hashlib.sha256(script_content.encode("utf-8")).hexdigest()
        if not record.success or record.script_sha256 != script_sha:
            return None
        return record

    async def _load_successful_simulation_result(self) -> SimulationResult | None:
        try:
            raw_result = await self.ctx.worker_client.read_file_optional(
                "simulation_result.json"
            )
            if raw_result is None:
                return None
            result = SimulationResult.model_validate_json(raw_result)
        except Exception as exc:
            logger.warning("persisted_simulation_result_invalid", error=str(exc))
            return None

        if not result.success:
            return None
        return result

    async def __call__(self, state: BenchmarkGeneratorState) -> BenchmarkGeneratorState:
        session_id = str(state.session.session_id)
        logger.info("coder_node_start", session_id=session_id)

        # Context construction
        validation_logs = "\n".join(state.session.validation_logs)
        if state.simulation_result and not state.simulation_result.valid:
            validation_logs += "\n" + "\n".join(state.simulation_result.logs)

        benchmark_definition_yaml = "# No benchmark_definition.yaml found."
        with suppress(Exception):
            benchmark_definition_yaml = (
                await self.ctx.worker_client.read_file_optional(
                    BENCHMARK_DEFINITION_FILE
                )
                or benchmark_definition_yaml
            )
        plan_input = (
            state.plan.model_dump_json() if state.plan else f"# No {PLAN_FILE} found."
        )
        if plan_input == f"# No {PLAN_FILE} found.":
            with suppress(Exception):
                plan_input = (
                    await self.ctx.worker_client.read_file_optional(PLAN_FILE)
                    or plan_input
                )

        inputs = {
            "prompt": state.session.prompt,
            "plan": plan_input,
            "benchmark_definition_yaml": benchmark_definition_yaml,
            "review_feedback": (
                state.review_feedback
                if state.session.status == SessionStatus.REJECTED
                else "No feedback provided."
            ),
            "validation_logs": validation_logs,
        }

        # Node uses ReAct for tool usage
        prediction, artifacts, journal_entry = await self._run_program(
            dspy.ReAct,
            BenchmarkCoderSignature,
            state,
            inputs,
            get_benchmark_tools,
            [
                SCRIPT_FILE,
                PLAN_FILE,
                "todo.md",
                "benchmark_definition.yaml",
            ],
            AgentName.BENCHMARK_CODER,
        )

        if not prediction and not artifacts:
            state.session.status = SessionStatus.REJECTED
            state.review_feedback = "Coder failed before producing required artifacts."
            state.session.validation_logs.append(
                "coder_execution: no prediction and no artifacts returned"
            )
            state.journal += f"\n[Coder] Failed: {journal_entry}"
            return state

        new_journal = (
            getattr(prediction, "journal", "No journal provided.")
            if prediction
            else "Validation failed, but some artifacts were created."
        )
        state.journal += f"\n[Coder] {new_journal}"
        state.messages.append(AIMessage(content=f"Work summary: {new_journal}"))

        # Retrieve script for further validation/simulation
        if SCRIPT_FILE in artifacts:
            state.current_script = artifacts[SCRIPT_FILE]
        else:
            with suppress(Exception):
                state.current_script = await self.ctx.worker_client.read_file(
                    SCRIPT_FILE
                )

        if not state.current_script or not state.current_script.strip():
            state.session.status = SessionStatus.REJECTED
            state.review_feedback = f"Coder handoff blocked: {SCRIPT_FILE} is missing after coder execution."
            state.session.validation_logs.append(
                f"reviewer_submission: missing {SCRIPT_FILE} after coder execution"
            )
            return state

        # Run Verification (Geometric + Physics)
        script = state.current_script
        if script:
            script_contract_violations = _script_contract_violations(script)
            if script_contract_violations:
                state.session.status = SessionStatus.REJECTED
                state.review_feedback = "Coder handoff blocked: " + "; ".join(
                    script_contract_violations
                )
                for violation in script_contract_violations:
                    state.session.validation_logs.append(
                        "reviewer_submission: " + violation
                    )
                return state

            logger.info("running_integrated_validation", session_id=session_id)
            try:
                val_res = None
                validation_record = await self._load_fresh_validation_record(
                    script_content=script
                )
                if validation_record is None:
                    val_res = await self.ctx.worker_client.validate(
                        script_path=SCRIPT_FILE
                    )
                else:
                    logger.info(
                        "reusing_fresh_validation_result", session_id=session_id
                    )

                if val_res is not None and not val_res.success:
                    validation_error = (
                        val_res.message or "geometric validation failed before submit"
                    )
                    state.session.status = SessionStatus.REJECTED
                    state.review_feedback = (
                        "Coder handoff blocked: geometric validation failed. "
                        + validation_error
                    )
                    state.session.validation_logs.append(
                        "reviewer_submission: " + validation_error
                    )
                    from shared.simulation.schemas import ValidationResult

                    state.simulation_result = ValidationResult(
                        valid=False,
                        cost=0,
                        logs=[f"Geometric validation failed: {val_res.message}"],
                        render_paths=[],
                        render_data=[],
                    )
                else:
                    # physics simulation
                    backend = get_default_simulator_backend()
                    try:
                        obj_data = yaml.safe_load(benchmark_definition_yaml)
                        if (
                            obj_data
                            and "physics" in obj_data
                            and "backend" in obj_data["physics"]
                        ):
                            backend = SimulatorBackendType(
                                obj_data["physics"]["backend"]
                            )
                    except Exception:
                        pass

                    sim_res = None
                    persisted_sim_result = (
                        await self._load_successful_simulation_result()
                    )
                    if persisted_sim_result is None:
                        sim_res = await self.ctx.worker_client.simulate(
                            script_path=SCRIPT_FILE, backend=backend
                        )
                    else:
                        logger.info(
                            "reusing_fresh_simulation_result", session_id=session_id
                        )

                    if sim_res is not None and sim_res.artifacts:
                        if isinstance(sim_res.artifacts, SimulationArtifacts):
                            if sim_res.artifacts.mjcf_content:
                                state.mjcf_content = sim_res.artifacts.mjcf_content
                        elif isinstance(sim_res.artifacts, dict):
                            state.mjcf_content = sim_res.artifacts.get(
                                "mjcf_content", ""
                            )
                    elif persisted_sim_result and persisted_sim_result.mjcf_content:
                        state.mjcf_content = persisted_sim_result.mjcf_content

                    if sim_res is not None and not sim_res.success:
                        simulation_error = (
                            sim_res.message or "physics simulation failed before submit"
                        )
                        state.session.status = SessionStatus.REJECTED
                        state.review_feedback = (
                            "Coder handoff blocked: physics simulation failed. "
                            + simulation_error
                        )
                        state.session.validation_logs.append(
                            "reviewer_submission: " + simulation_error
                        )
                        from shared.simulation.schemas import ValidationResult

                        state.simulation_result = ValidationResult(
                            valid=False,
                            cost=0,
                            logs=[f"Physics simulation failed: {sim_res.message}"],
                            render_paths=[],
                            render_data=[],
                        )
                    else:
                        render_paths: list[str] = []
                        validation_logs = ["Validation passed."]
                        if sim_res is not None and sim_res.artifacts:
                            if isinstance(sim_res.artifacts, SimulationArtifacts):
                                render_paths = sim_res.artifacts.render_paths
                            elif isinstance(sim_res.artifacts, dict):
                                render_paths = sim_res.artifacts.get("render_paths", [])
                        elif persisted_sim_result is not None:
                            render_paths = list(persisted_sim_result.render_paths)
                            validation_logs = [persisted_sim_result.summary]

                        render_data = await self._download_render_data(
                            render_paths=render_paths,
                            session_id=session_id,
                        )

                        from shared.simulation.schemas import ValidationResult

                        state.simulation_result = ValidationResult(
                            valid=True,
                            cost=0,
                            logs=validation_logs,
                            render_paths=render_paths,
                            render_data=render_data,
                        )

                        handoff_err = await validate_reviewer_handover(
                            self.ctx.worker_client,
                            manifest_path=".manifests/benchmark_review_manifest.json",
                            expected_stage=AgentName.BENCHMARK_REVIEWER,
                            require_git_revision=True,
                        )
                        if handoff_err is None:
                            logger.info(
                                "reusing_existing_benchmark_handover",
                                session_id=session_id,
                            )
                            state.session.status = SessionStatus.PLANNED
                            state.review_feedback = None
                            return state

                        # Control-plane handoff submit is executed only after
                        # validate+simulate pass. benchmark_script.py itself stays a pure
                        # importable module with no in-module submission path.
                        submit_res = await self.ctx.worker_client.submit(
                            script_path=SCRIPT_FILE,
                            reviewer_stage=AgentName.BENCHMARK_REVIEWER,
                            episode_id=state.episode_id,
                        )
                        logger.info(
                            "benchmark_coder_submit_result",
                            session_id=session_id,
                            success=getattr(submit_res, "success", None),
                            message=getattr(submit_res, "message", None),
                        )
                        await self.ctx.worker_client._sync_handover_artifacts_to_light(
                            submit_res
                        )
                        if not submit_res.success:
                            state.session.status = SessionStatus.REJECTED
                            state.review_feedback = (
                                "Reviewer handoff blocked: "
                                f"{submit_res.message or 'submit_for_review failed.'}"
                            )
                            state.session.validation_logs.append(
                                "reviewer_submission: "
                                f"{submit_res.message or 'submit_for_review failed.'}"
                            )
                        else:
                            state.session.status = SessionStatus.PLANNED
                            state.review_feedback = None
            except Exception as e:
                # Cancellation during orchestration shutdown should not be recorded
                # as a backend error-log regression.
                if isinstance(e, asyncio.CancelledError):
                    logger.info("integrated_validation_cancelled")
                else:
                    logger.error(
                        "integrated_validation_error",
                        error=str(e),
                        session_id=str(state.session.session_id),
                    )
                    state.session.status = SessionStatus.FAILED

        return state


@type_check
async def coder_node(state: BenchmarkGeneratorState) -> BenchmarkGeneratorState:
    from controller.config.settings import settings as global_settings

    worker_light_url = global_settings.worker_light_url
    ctx = SharedNodeContext.create(
        worker_light_url=worker_light_url,
        session_id=_benchmark_worker_session_id(state),
        episode_id=state.episode_id,
        agent_role=AgentName.BENCHMARK_CODER,
    )
    node = BenchmarkCoderNode(context=ctx)
    return await node(state)


@type_check
async def cots_search_node(state: BenchmarkGeneratorState) -> BenchmarkGeneratorState:
    from controller.config.settings import settings as global_settings

    worker_light_url = global_settings.worker_light_url
    ctx = SharedNodeContext.create(
        worker_light_url=worker_light_url,
        session_id=_benchmark_worker_session_id(state),
        episode_id=state.episode_id,
        agent_role=AgentName.COTS_SEARCH,
    )
    node = COTSSearchNode(context=ctx)
    summary, _ = await node.run_search(state=state, prompt=state.session.prompt)
    state.messages.append(
        AIMessage(content=f"COTS Search summary: {summary or 'No summary provided.'}")
    )
    return state


class BenchmarkReviewerSignature(dspy.Signature):
    """DSPy signature for the benchmark reviewer."""

    theme = dspy.InputField()
    prompt = dspy.InputField()
    plan_md = dspy.InputField()
    objectives = dspy.InputField()
    simulation_logs = dspy.InputField()
    review: ReviewResult = dspy.OutputField()


@type_check
class BenchmarkReviewerNode(BaseNode):
    """Refactored Benchmark Reviewer using BaseNode."""

    async def _enforce_render_inspection_gate(
        self, review: ReviewResult
    ) -> ReviewResult:
        if review.decision != ReviewDecision.APPROVED:
            return review
        render_paths = await self._list_render_media_paths()
        if not render_paths:
            return review
        inspected_render_count = self._count_inspected_render_media_paths(render_paths)
        if inspected_render_count > 0:
            return review
        fixes = list(review.required_fixes or [])
        fixes.append(
            "Inspect at least one current-revision render via inspect_media(path) "
            "before approving."
        )
        return review.model_copy(
            update={
                "decision": ReviewDecision.REJECTED,
                "reason": (
                    "Approval blocked: current-revision renders exist but the "
                    "reviewer did not inspect any of them with inspect_media(path)."
                ),
                "required_fixes": fixes,
            }
        )

    async def __call__(self, state: BenchmarkGeneratorState) -> BenchmarkGeneratorState:
        logger.info("reviewer_node_start", round=state.review_round)

        submit_err = await self._ensure_submit_for_review_succeeded()
        if submit_err:
            state.review_decision = ReviewDecision.REJECTED
            state.review_feedback = f"Rejected: {submit_err}"
            state.journal += f"\n[Reviewer] {submit_err}"
            return state

        # Read context files
        plan_md = f"# No {PLAN_FILE} found."
        with suppress(Exception):
            plan_md = (
                await self.ctx.worker_client.read_file_optional(PLAN_FILE) or plan_md
            )

        objectives = "# No benchmark_definition.yaml found."
        with suppress(Exception):
            objectives = (
                await self.ctx.worker_client.read_file_optional(
                    "benchmark_definition.yaml"
                )
                or objectives
            )

        review_round = await self._next_review_round("benchmark-execution-review")

        def get_reviewer_tools(fs, session_id):
            tools = get_benchmark_tools(fs, session_id)
            final_tools = []
            for t in tools:
                name = getattr(t, "name", getattr(t, "__name__", None))
                if name != "edit_file":
                    final_tools.append(t)

            return filter_tools_for_agent(fs, final_tools)

        inputs = {
            "theme": state.plan.theme if state.plan else "Unknown",
            "prompt": state.session.prompt,
            "plan_md": plan_md,
            "objectives": objectives,
            "simulation_logs": str(
                state.simulation_result.logs if state.simulation_result else []
            ),
        }

        try:
            prediction, _, journal_entry = await self._run_program(
                dspy.ReAct,
                BenchmarkReviewerSignature,
                state,
                inputs,
                get_reviewer_tools,
                [],
                AgentName.BENCHMARK_REVIEWER,
            )

            if not prediction:
                state.review_decision = ReviewDecision.REJECTED
                state.review_feedback = "Error: Reviewer failed to complete."
                state.journal += f"\n[Reviewer] Failed: {journal_entry}"
                return state

            review = ReviewResult.model_validate(prediction.review)
            review = await self._enforce_render_inspection_gate(review)
            (
                review_decision_path,
                review_comments_path,
            ) = await self._persist_review_result(
                review,
                "benchmark-execution-review",
                round_number=review_round,
            )
            state.review_decision = review.decision
            state.review_feedback = f"{review.decision.value}: {review.reason}"
            state.journal += (
                f"\n[Reviewer] {state.review_feedback}\n"
                f"Decision file: {review_decision_path}\n"
                f"Comments file: {review_comments_path}\n"
                f"{journal_entry}"
            )
            if review.required_fixes:
                state.review_feedback += "\nFixes: " + ", ".join(review.required_fixes)
            review_id = uuid.uuid4().hex
            await record_worker_events(
                episode_id=state.episode_id,
                events=[
                    ReviewDecisionEvent(
                        decision=review.decision,
                        reason=state.review_feedback,
                        review_id=review_id,
                        evidence_stats={
                            "has_sim_report": True,
                            "review_decision_path": review_decision_path,
                            "review_comments_path": review_comments_path,
                        },
                        checklist=review.checklist,
                    )
                ],
            )
        except Exception as e:
            logger.warning("benchmark_reviewer_node_failed", error=str(e))
            state.review_decision = ReviewDecision.REJECTED
            state.review_feedback = "Rejected: Internal error"
            await asyncio.sleep(2)

        return state

    async def _ensure_submit_for_review_succeeded(self) -> str | None:
        handoff_err = await validate_reviewer_handover(
            self.ctx.worker_client,
            manifest_path=".manifests/benchmark_review_manifest.json",
            expected_stage=AgentName.BENCHMARK_REVIEWER,
            require_git_revision=True,
        )
        if handoff_err:
            return f"Benchmark reviewer blocked: {handoff_err}"
        return None


@type_check
async def reviewer_node(state: BenchmarkGeneratorState) -> BenchmarkGeneratorState:
    from controller.config.settings import settings as global_settings

    worker_light_url = global_settings.worker_light_url
    ctx = SharedNodeContext.create(
        worker_light_url=worker_light_url,
        session_id=_benchmark_worker_session_id(state),
        episode_id=state.episode_id,
        agent_role=AgentName.BENCHMARK_REVIEWER,
    )
    node = BenchmarkReviewerNode(context=ctx)
    return await node(state)
