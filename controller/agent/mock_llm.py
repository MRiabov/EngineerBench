import json
import re
from contextlib import suppress
from functools import lru_cache
from types import SimpleNamespace
from typing import Any

import dspy
import structlog

from controller.agent.mock_scenarios import load_integration_mock_scenarios
from shared.enums import AgentName

logger = structlog.get_logger(__name__)

PLANNER_AGENTS = {
    AgentName.ENGINEER_PLANNER,
    AgentName.BENCHMARK_PLANNER,
}
CODER_AGENTS = {
    AgentName.ENGINEER_CODER,
    AgentName.BENCHMARK_CODER,
}
REVIEWER_AGENTS = {
    AgentName.ENGINEER_PLAN_REVIEWER,
    AgentName.BENCHMARK_PLAN_REVIEWER,
    AgentName.BENCHMARK_REVIEWER,
    AgentName.ENGINEER_EXECUTION_REVIEWER,
}


@lru_cache(maxsize=1)
def _cached_integration_mock_scenarios() -> dict[str, dict[str, Any]]:
    """
    Load the integration mock scenario corpus once per process.

    Integration runs instantiate a fresh MockDSPyLM per agent node, so without
    this cache we repeatedly re-parse the same YAML corpus on every node setup.
    """

    return load_integration_mock_scenarios()


class MockDSPyLM(dspy.LM):
    """Mock DSPy LM using per-test integration scenario files keyed by session_id."""

    node_type: AgentName | None
    _transcript_states: dict[str, int]  # session_id -> entry_idx

    def __init__(
        self,
        session_id: str | None = None,
        node_type: AgentName | str | None = None,
        **kwargs,
    ):
        super().__init__(model="mock-dspy-model", **kwargs)
        self._transcript_states = {}  # session_id -> entry_idx
        self.session_id = session_id or "default-session"
        self.node_type = self._normalize_agent_name(node_type)
        self.provider = "openai"
        self.scenarios = _cached_integration_mock_scenarios()
        self._call_counts = {}  # Tracks calls per node key to detect loops
        self._tool_progress = {}  # Tracks completed tool steps from trajectory text
        # Tracks repeated LM invocations without tool-observation progress.
        self._stall_counts = {}

    def __call__(
        self,
        prompt: str | None = None,
        messages: list[dict[str, Any]] | None = None,
        **_kwargs,
    ):
        logger.info(
            "mock_dspy_lm_call",
            session_id=self.session_id,
            explicit_node=self.node_type,
        )

        full_text = self._get_full_text(prompt, messages)
        logger.info("mock_dspy_full_text", text=full_text)

        # 1. Resolve scenario from session_id only (no prompt heuristics).
        scenario_id = self._get_scenario_id(full_text)
        # Final check if session_id is a direct match but was missed by _get_scenario_id
        if scenario_id not in self.scenarios and self.session_id in self.scenarios:
            scenario_id = self.session_id

        if scenario_id not in self.scenarios:
            raise ValueError(
                f"MockDSPyLM: Scenario '{scenario_id}' not found in integration mock scenarios "
                f"for session_id='{self.session_id}'. "
                f"Available scenarios: {list(self.scenarios.keys())}"
            )
        scenario = self.scenarios[scenario_id]

        # 2. Node type must be explicit and map to AgentName exactly.
        node_key = self._normalize_agent_name(self.node_type)
        if node_key is None:
            raise ValueError(
                "MockDSPyLM requires explicit node_type AgentName during integration tests."
            )

        # Detect if JSON is requested or if we should provide it for structured nodes
        low_text = full_text.lower()
        is_json_requested = (
            ("output fields" in low_text or "outputs will be" in low_text)
            and "json" in low_text
        ) or "respond with a json object" in low_text

        # Extract expected structured output fields for non-tool final responses.
        expected_fields = []

        # Always try to detect fields from text if they exist
        match = re.search(
            r"(?:Expected to find output fields in the LM response|Expected output fields)\s*:\s*\[([^\]]+)\]",
            full_text,
            flags=re.IGNORECASE,
        )
        if match:
            expected_fields = [f.strip() for f in match.group(1).split(",")]
        else:
            for field in [
                "reasoning",
                "thought",
                "summary",
                "review",
                "journal",
                "plan",
                "finished",
                "next_thought",
                "next_tool_name",
                "next_tool_args",
            ]:
                if field in full_text:
                    expected_fields.append(field)

        expected_fields = list(dict.fromkeys(expected_fields))

        # WP10: Detect expected fields from JSON template if empty
        if is_json_requested and not expected_fields:
            expected_fields = self._detect_expected_fields_from_json(full_text)
            logger.info("mock_dspy_detected_fields_from_json", fields=expected_fields)

        # Standard ReAct with TypedPredictor uses field-based formatting [[ ## field ## ]]
        is_json = is_json_requested

        logger.info(
            "mock_dspy_expected_fields", fields=expected_fields, is_json=is_json
        )

        lookup_key = node_key.value
        node_data: dict[str, Any] = scenario.get(lookup_key, {})
        logger.info(
            "mock_dspy_lm_data_found",
            scenario=scenario_id,
            node=lookup_key,
            has_data=bool(node_data),
        )

        # Track explicit tool progress from trajectory markers, not LM call count.
        # DSPy can invoke LM multiple times per step, so call count alone is unstable.
        # We count both the field-based markers and the standard ReAct Observation markers.
        custom_markers = re.findall(
            r"\[\[\s*##\s*observation_\d+\s*##\s*\]\]", full_text
        )
        json_markers = re.findall(r"\bobservation_(\d+)\b", full_text)
        standard_markers = re.findall(r"Observation:", full_text, re.IGNORECASE)
        completed_tools = max(
            len(custom_markers),
            len(set(json_markers)),
        ) + len(standard_markers)
        self._tool_progress[lookup_key] = completed_tools

        # 3. Handle multi-turn state and loop protection
        count = self._call_counts.get(lookup_key, 0)
        # Idempotency check: if prompt is identical to last call for this node, don't increment
        last_prompt = getattr(self, "_last_prompt", {}).get(lookup_key)
        if last_prompt == full_text:
            logger.info("mock_dspy_lm_idempotent_call", node=lookup_key)
        else:
            self._call_counts[lookup_key] = count + 1
            if not hasattr(self, "_last_prompt"):
                self._last_prompt = {}
            self._last_prompt[lookup_key] = full_text

        call_index = self._call_counts.get(lookup_key, 0)

        # Optional assertions for integration hardening.
        self._validate_expected_llm_inputs(
            node_key=lookup_key,
            node_data=node_data,
            full_text=full_text,
            call_index=call_index,
        )
        self._validate_expected_tool_calls(
            node_key=lookup_key,
            node_data=node_data,
            full_text=full_text,
        )
        self._validate_expected_tool_outputs(
            node_key=lookup_key,
            node_data=node_data,
            full_text=full_text,
        )

        # 3. Handle Transcript mode if present in scenario
        if "transcript" in scenario:
            transcript_resp = self._handle_transcript(
                scenario, node_key, full_text, is_json, expected_fields
            )
            if transcript_resp:
                return transcript_resp

        # For non-transcript scripted tool sequences, detect true no-progress stalls.
        # DSPy can invoke LM multiple times per step, so raw call count is insufficient.
        tool_calls = node_data.get("tool_calls", [])
        prev_progress = self._tool_progress.get(f"{lookup_key}__prev", -1)
        stalled_calls = self._stall_counts.get(lookup_key, 0)
        if completed_tools > prev_progress:
            stalled_calls = 0
        else:
            stalled_calls += 1
        self._stall_counts[lookup_key] = stalled_calls
        self._tool_progress[f"{lookup_key}__prev"] = completed_tools

        if stalled_calls > 5 and (not tool_calls or completed_tools >= len(tool_calls)):
            logger.error(
                "mock_dspy_lm_loop_detected",
                node=lookup_key,
                stalled_calls=stalled_calls,
                call_count=call_index,
                completed_tools=completed_tools,
                expected_tool_calls=len(tool_calls),
                session_id=self.session_id,
            )
            raise ValueError(
                f"MockDSPyLM loop detected for node={lookup_key}: "
                f"no tool-progress for {stalled_calls} calls "
                f"(completed_tools={completed_tools}, expected_tool_calls={len(tool_calls)})."
            )

        # 4. Handle legacy multi-turn state and loop protection
        # Only force finish on observation when explicit tool calls are exhausted.
        tool_calls = node_data.get("tool_calls", [])
        tool_progress = self._tool_progress.get(lookup_key, 0)
        if self._is_finishing(full_text) and (
            not tool_calls or tool_progress >= len(tool_calls)
        ):
            return self._handle_finish(node_key, node_data, is_json, expected_fields)

        return self._handle_action(node_key, node_data, is_json, expected_fields)

    @staticmethod
    def _normalize_agent_name(node_type: AgentName | str | None) -> AgentName | None:
        if node_type is None:
            return None
        if isinstance(node_type, AgentName):
            return node_type
        return AgentName(node_type.strip())

    @staticmethod
    def _scenario_lookup_keys(node_key: AgentName) -> list[str]:
        return [node_key.value]

    def _handle_transcript(
        self,
        scenario: dict,
        node_key: AgentName,
        full_text: str,
        is_json: bool,
        expected_fields: list[str],
    ) -> list[str] | None:
        transcript = scenario.get("transcript", [])
        entry_idx = self._transcript_states.get(self.session_id, 0)
        target_node = node_key.value

        # Find the next matching entry in transcript starting from current state
        found_idx = -1
        for i in range(entry_idx, len(transcript)):
            if transcript[i].get("node") == target_node:
                found_idx = i
                break

        if found_idx == -1:
            logger.info(
                "mock_transcript_node_not_found", node=node_key, entry_idx=entry_idx
            )
            return None

        # Reset states if we are starting a new session/scenario entry to ensure idempotency
        # However, entry_idx is class-level. We should probably use (session_id, node_key) if we want multi-node turns.
        # But for now, entry_idx is enough for sequential node turns.

        self._transcript_states[self.session_id] = found_idx
        entry = transcript[found_idx]
        steps = entry.get("steps", [])

        # Step selection by counting observations in the trajectory only.
        # Counting across full prompt text is unstable because prompt instructions
        # often include "Observation:" examples that are not real tool results.
        trajectory_text = self._extract_trajectory_text(full_text)
        standard_markers = re.findall(r"Observation:", trajectory_text, re.IGNORECASE)
        completed_tools = len(
            re.findall(r"\[\[\s*##\s*observation_\d+\s*##\s*\]\]", trajectory_text)
        ) + len(standard_markers)

        step_idx = min(completed_tools, len(steps) - 1)
        step_data = steps[step_idx]

        logger.info(
            "mock_transcript_step",
            node=node_key.value,
            entry_idx=found_idx,
            step_idx=step_idx,
            completed_tools=completed_tools,
        )

        # Validate observation if previous step had expected_observation
        if step_idx > 0:
            prev_step = steps[step_idx - 1]
            expected_obs = prev_step.get("expected_observation")
            if expected_obs:
                # Regex to find observations. Handles both [[ ## observation_N ## ]] and Observation:
                obs_matches = re.findall(
                    r"(?:Observation:|\[\[\s*##\s*observation_\d+\s*##\s*\]\])\s*(.*?)(?=\n\s*\[\[\s*##|\Z)",
                    full_text,
                    re.DOTALL | re.IGNORECASE,
                )
                if obs_matches:
                    actual_obs = obs_matches[-1].strip()
                    matches, preview = self._observation_matches_expected(
                        expected=expected_obs,
                        actual=actual_obs,
                    )
                    if not matches:
                        logger.warning(
                            "mock_transcript_observation_mismatch",
                            node=node_key.value,
                            step=step_idx - 1,
                            expected=expected_obs,
                            actual=preview,
                        )

        # If this step is 'finished', we prepare to move to next entry on NEXT call
        if step_data.get("finished"):
            self._transcript_states[self.session_id] = found_idx + 1

        # Use tool_override if it's a tool-calling step
        tool_override = None
        finished = step_data.get("finished", False)
        if not step_data.get("finished"):
            tool_name = step_data.get("tool_name")
            if tool_name:
                tool_override = (tool_name, step_data.get("tool_args", {}))

        return self._generate_response(
            node_key,
            step_data,
            is_json,
            finished=finished,
            expected_fields=expected_fields,
            tool_override=tool_override,
        )

    @staticmethod
    def _extract_trajectory_text(full_text: str) -> str:
        marker_pattern = re.compile(
            r"\[\[\s*##\s*trajectory\s*##\s*\]\]", re.IGNORECASE
        )
        matches = list(marker_pattern.finditer(full_text))
        if matches:
            return full_text[matches[-1].end() :]

        # ReAct prompts often place tool history under this header.
        lower = full_text.lower()
        idx = lower.rfind("past interactions:")
        if idx != -1:
            return full_text[idx:]

        return full_text

    def _detect_expected_fields_from_json(self, text: str) -> list[str]:
        """Detect expected JSON keys from a template in the prompt."""
        # Only look in the last part of the prompt where the output template is
        search_text = text[-2000:] if len(text) > 2000 else text

        # Find blocks that look like JSON templates: { "key": "{key}", ... }
        # We look for "key": and extract the key.
        keys = re.findall(r'"([^"]+)"\s*:', search_text)

        logger.debug("mock_dspy_all_json_keys_found", keys=keys)

        # Filter out common false positives if needed, but for now just take unique ones
        whitelist = [
            "reasoning",
            "thought",
            "summary",
            "plan",
            "review",
            "journal",
            "summarized_journal",
            "answer",
        ]
        return [k for k in list(dict.fromkeys(keys)) if k in whitelist]

    def _get_full_text(
        self, prompt: str | None, messages: list[dict[str, Any]] | None
    ) -> str:
        text = str(prompt or "")
        if messages:
            for msg in messages:
                text += str(msg.get("content", ""))
        return text

    @staticmethod
    def _message_content_text(content: Any) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            chunks: list[str] = []
            for item in content:
                if isinstance(item, str):
                    chunks.append(item)
                elif isinstance(item, dict):
                    text = item.get("text")
                    if isinstance(text, str):
                        chunks.append(text)
            return "\n".join(chunks)
        if content is None:
            return ""
        return str(content)

    def _native_messages_text(self, messages: list[dict[str, Any]]) -> str:
        chunks: list[str] = []
        for msg in messages:
            role = str(msg.get("role") or "")
            content = self._message_content_text(msg.get("content"))
            if content:
                chunks.append(f"{role}: {content}")
        return "\n".join(chunks)

    def _native_tool_observations(self, messages: list[dict[str, Any]]) -> list[str]:
        observations: list[str] = []
        for msg in messages:
            if str(msg.get("role")) != "tool":
                continue
            content = self._message_content_text(msg.get("content")).strip()
            observations.append(content)
        return observations

    def _native_tool_call_turns(self, messages: list[dict[str, Any]]) -> int:
        """
        Count assistant turns that emitted native tool calls.

        Some native tool loop paths re-enter before the corresponding tool
        response is present in the message list, so transcript progress must be
        able to advance from either the tool response or the assistant tool-call
        turn itself.
        """

        tool_call_turns = 0
        for msg in messages:
            if str(msg.get("role")) != "assistant":
                continue
            tool_calls = msg.get("tool_calls")
            if isinstance(tool_calls, list) and tool_calls:
                tool_call_turns += len(tool_calls)
        return tool_call_turns

    @classmethod
    def _observation_candidates(cls, observation: Any) -> list[str]:
        candidates: list[str] = []

        def add(value: Any) -> None:
            if value is None:
                return
            text = str(value).strip()
            if not text:
                return
            if text not in candidates:
                candidates.append(text)
            lowered = text.lower()
            if lowered not in candidates:
                candidates.append(lowered)

        def collect(value: Any) -> None:
            if value is None:
                return

            if isinstance(value, bool):
                add("true" if value else "false")
                add("success" if value else "failure")
                return

            if isinstance(value, (int, float)):
                add(value)
                return

            if isinstance(value, str):
                text = value.strip()
                if not text:
                    return
                add(text)
                lowered = text.lower()
                if lowered == "true":
                    collect(True)
                    return
                if lowered == "false":
                    collect(False)
                    return

                with suppress(Exception):
                    parsed = json.loads(text)
                    if parsed != value:
                        collect(parsed)

                lines = [line.strip() for line in text.splitlines() if line.strip()]
                if len(lines) > 1:
                    collect(lines[0])
                    collect(lines[-1])
                return

            if isinstance(value, dict):
                for key in ("success", "ok"):
                    if isinstance(value.get(key), bool):
                        collect(value[key])
                for key in ("status", "message", "reason", "detail"):
                    if key in value:
                        collect(value[key])

                stdout = value.get("stdout")
                if isinstance(stdout, str):
                    collect(stdout)
                stderr = value.get("stderr")
                if isinstance(stderr, str) and stderr.strip():
                    collect(stderr)
                return

            add(value)

        collect(observation)
        return candidates

    @classmethod
    def _observation_matches_expected(
        cls, *, expected: str, actual: Any
    ) -> tuple[bool, str]:
        normalized_expected = str(expected).strip()
        if not normalized_expected:
            return True, ""

        candidates = cls._observation_candidates(actual)
        expected_candidates = cls._observation_candidates(normalized_expected)
        expected_lowers = {candidate.lower() for candidate in expected_candidates}

        for candidate in candidates:
            candidate_lower = candidate.lower()
            if candidate_lower in expected_lowers:
                return True, candidate
            if any(
                expected_lower in candidate_lower for expected_lower in expected_lowers
            ):
                return True, candidate

        preview = candidates[0] if candidates else str(actual).strip()
        return False, preview

    def _get_scenario_id(self, full_text: str | None = None) -> str:
        """Extract a strict integration scenario ID from the session or prompt."""
        if full_text:
            explicit_match = re.search(r"\bINT-\d{3}\b", full_text)
            if explicit_match:
                explicit_id = explicit_match.group(0)
                if explicit_id in self.scenarios:
                    return explicit_id

        # Prefer exact scenario key before any normalization.
        if self.session_id in self.scenarios:
            return self.session_id

        parts = self.session_id.split("-")
        if len(parts) > 1:
            # If the last part looks like a random hash or short hex (e.g. 'abcd', '1234')
            # and there are at least 2 other parts (e.g. 'INT-002-abcd'), strip it.
            last = parts[-1].lower()
            is_noise = (
                len(last) <= 8 and all(c in "0123456789abcdef" for c in last)
            ) or last.isdigit()
            if is_noise and len(parts) > 2:
                scenario = "-".join(parts[:-1])
                # Prefer exact stripped scenario key to avoid prefix/substring ambiguity.
                if scenario in self.scenarios:
                    return scenario
                # Normalize INT scenario IDs.
                # Examples:
                # - INT-002-abcd -> INT-002
                # - INT-184-benchmark-abcd -> INT-184
                if scenario.startswith("INT-"):
                    scenario_parts = scenario.split("-")
                    return scenario_parts[0] + "-" + scenario_parts[1]
                return scenario

            # Special case: exact scenario IDs without a random suffix stay as-is.
            if self.session_id in self.scenarios:
                return self.session_id

        raise ValueError(
            "MockDSPyLM could not resolve a strict integration scenario ID from "
            f"session_id='{self.session_id}'. Provide an explicit INT-### marker in "
            "the prompt or use an exact scenario ID."
        )

    def _native_call_index(self, node_key: str, full_text: str) -> int:
        count = self._call_counts.get(node_key, 0)
        last_prompt = getattr(self, "_last_prompt", {}).get(node_key)
        if last_prompt == full_text:
            logger.info("mock_native_tool_idempotent_call", node=node_key)
        else:
            self._call_counts[node_key] = count + 1
            if not hasattr(self, "_last_prompt"):
                self._last_prompt = {}
            self._last_prompt[node_key] = full_text
        return self._call_counts.get(node_key, 0)

    @staticmethod
    def _native_message(
        *, assistant_text: str, tool_name: str, tool_args: dict[str, Any], call_id: str
    ) -> SimpleNamespace:
        return SimpleNamespace(
            content=assistant_text,
            tool_calls=[
                {
                    "id": call_id,
                    "type": "function",
                    "function": {
                        "name": tool_name,
                        "arguments": json.dumps(tool_args or {}),
                    },
                }
            ],
        )

    def _native_finish_payload(
        self,
        *,
        node_key: AgentName,
        node_data: dict[str, Any],
        finish_fields: list[str],
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        for field in finish_fields:
            if field == "reasoning":
                payload[field] = node_data.get(
                    "reasoning", "Verified all requirements."
                )
            elif field == "summary":
                payload[field] = node_data.get("summary", "Task complete.")
            elif field == "journal":
                payload[field] = node_data.get("journal", "Work completed.")
            elif field == "review":
                payload[field] = node_data.get(
                    "review",
                    {
                        "decision": "APPROVED",
                        "reason": "Verified.",
                        "required_fixes": [],
                    },
                )
            elif field == "plan":
                payload[field] = node_data.get(
                    "plan",
                    {
                        "theme": "benchmark_test",
                        "target_object_properties": {},
                        "environment_perturbations": {},
                        "difficulty_score": 0.5,
                        "reasoning": "Default mock benchmark plan.",
                    },
                )
            else:
                payload[field] = node_data.get(field)

        if (
            node_key in PLANNER_AGENTS
            and "plan" in finish_fields
            and not payload.get("plan")
        ):
            payload["plan"] = {
                "theme": "benchmark_test",
                "target_object_properties": {},
                "environment_perturbations": {},
                "difficulty_score": 0.5,
                "reasoning": "Default mock benchmark plan.",
            }

        return payload

    def native_tool_completion(
        self,
        *,
        messages: list[dict[str, Any]],
        node_type: AgentName,
        finish_fields: list[str],
        completion_tool_name: str = "finish",
    ) -> SimpleNamespace:
        # Native tool loop calls do not pass the original prompt separately, so
        # resolve the scenario from the synthesized message text instead of
        # falling back to the generic UUID benchmark scenario.
        full_text = self._native_messages_text(messages)
        scenario_id = self._get_scenario_id(full_text)
        if scenario_id not in self.scenarios:
            raise ValueError(
                f"MockDSPyLM: Scenario '{scenario_id}' not found in integration mock scenarios "
                f"for session_id='{self.session_id}'. "
                f"Available scenarios: {list(self.scenarios.keys())}"
            )

        scenario = self.scenarios[scenario_id]
        node_key = self._normalize_agent_name(node_type)
        if node_key is None:
            raise ValueError("native_tool_completion requires explicit node_type.")

        call_index = self._native_call_index(node_key.value, full_text)
        node_data: dict[str, Any] = scenario.get(node_key.value, {})

        self._validate_expected_llm_inputs(
            node_key=node_key.value,
            node_data=node_data,
            full_text=full_text,
            call_index=call_index,
        )

        observations = self._native_tool_observations(messages)
        # Transcript scenarios must advance only after tool responses are
        # actually present. Counting assistant tool-call turns here can move
        # the transcript forward on a blocked finish call and skip the real
        # submit_plan step on short planner traces.
        completed_tools = len(observations)
        self._tool_progress[node_key.value] = completed_tools

        if "transcript" in scenario:
            transcript = scenario.get("transcript", [])
            entry_idx = self._transcript_states.get(self.session_id, 0)
            found_idx = -1
            for i in range(entry_idx, len(transcript)):
                if transcript[i].get("node") == node_key.value:
                    found_idx = i
                    break

            if found_idx == -1:
                prev_idx = entry_idx - 1
                if 0 <= prev_idx < len(transcript):
                    prev_entry = transcript[prev_idx]
                    prev_steps = prev_entry.get("steps", [])
                    last_step = prev_steps[-1] if prev_steps else {}
                    if prev_entry.get("node") == node_key.value and last_step.get(
                        "finished"
                    ):
                        logger.info(
                            "mock_native_transcript_idempotent_finish",
                            node=node_key.value,
                            entry_idx=prev_idx,
                        )
                        return self._native_message(
                            assistant_text=last_step.get("thought")
                            or last_step.get("reasoning", "Task complete."),
                            tool_name=completion_tool_name,
                            tool_args=self._native_finish_payload(
                                node_key=node_key,
                                node_data=last_step,
                                finish_fields=finish_fields,
                            ),
                            call_id=f"mock_{completion_tool_name}_{node_key.value}_idempotent",
                        )

                raise ValueError(
                    f"MockDSPyLM transcript node not found for native tool call: {node_key.value}"
                )

            self._transcript_states[self.session_id] = found_idx
            entry = transcript[found_idx]
            steps = entry.get("steps", [])
            step_idx = min(completed_tools, len(steps) - 1)
            step_data = steps[step_idx]

            logger.info(
                "mock_native_transcript_step",
                node=node_key.value,
                entry_idx=found_idx,
                step_idx=step_idx,
                completed_tools=completed_tools,
            )

            if step_idx > 0:
                prev_step = steps[step_idx - 1]
                expected_obs = prev_step.get("expected_observation")
                if expected_obs and observations:
                    actual_obs = observations[-1].strip()
                    matches, preview = self._observation_matches_expected(
                        expected=expected_obs,
                        actual=actual_obs,
                    )
                    if not matches:
                        logger.warning(
                            "mock_native_transcript_observation_mismatch",
                            node=node_key.value,
                            step=step_idx - 1,
                            expected=expected_obs,
                            actual=preview,
                        )

            assistant_text = step_data.get("thought") or step_data.get(
                "reasoning", "Task in progress."
            )
            if step_data.get("finished"):
                self._transcript_states[self.session_id] = found_idx + 1
                return self._native_message(
                    assistant_text=assistant_text,
                    tool_name=completion_tool_name,
                    tool_args=self._native_finish_payload(
                        node_key=node_key,
                        node_data=step_data,
                        finish_fields=finish_fields,
                    ),
                    call_id=f"mock_{completion_tool_name}_{node_key.value}_{step_idx}",
                )

            tool_name = step_data.get("tool_name")
            if not tool_name:
                raise ValueError(
                    f"Transcript step missing tool_name for native tool call: {node_key.value}"
                )
            return self._native_message(
                assistant_text=assistant_text,
                tool_name=tool_name,
                tool_args=step_data.get("tool_args", {}) or {},
                call_id=f"mock_tool_{node_key.value}_{step_idx}",
            )

        tool_calls = node_data.get("tool_calls", [])
        tool_progress = self._tool_progress.get(node_key.value, 0)
        thought = node_data.get("thought", "Task in progress.")

        if tool_progress < len(tool_calls):
            tc = tool_calls[tool_progress]
            return self._native_message(
                assistant_text=tc.get("thought", thought),
                tool_name=tc.get("name"),
                tool_args=tc.get("input", {}) or {},
                call_id=f"mock_tool_{node_key.value}_{tool_progress}",
            )

        return self._native_message(
            assistant_text=thought,
            tool_name=completion_tool_name,
            tool_args=self._native_finish_payload(
                node_key=node_key,
                node_data=node_data,
                finish_fields=finish_fields,
            ),
            call_id=f"mock_{completion_tool_name}_{node_key.value}_{tool_progress}",
        )

    def _is_finishing(self, text: str) -> bool:
        low_text = text.lower()
        # dspy.ReAct adds "Observation:" to the trajectory.
        return (
            "stdout:" in low_text
            or "stderr:" in low_text
            or "observation:" in low_text
            or "past interactions:" in low_text
        )

    def _handle_finish(
        self,
        node_key: AgentName,
        node_data: dict,
        is_json: bool,
        expected_fields: list[str],
    ):
        return self._generate_response(
            node_key, node_data, is_json, finished=True, expected_fields=expected_fields
        )

    def _handle_action(
        self,
        node_key: AgentName,
        node_data: dict,
        is_json: bool,
        expected_fields: list[str],
    ):
        # Force finish for reviewer to avoid loops in mock
        force_finish = node_key in REVIEWER_AGENTS

        count = self._call_counts.get(node_key, 0)
        tool_calls = node_data.get("tool_calls", [])

        # When explicit tool calls exist, continue until all calls are exhausted.
        if tool_calls:
            tool_progress = self._tool_progress.get(node_key, 0)
            should_finish = tool_progress >= len(tool_calls)
        else:
            should_finish = node_data.get("finished", force_finish) or count > 1

        return self._generate_response(
            node_key,
            node_data,
            is_json,
            finished=should_finish,
            expected_fields=expected_fields,
        )

    def _generate_response(
        self,
        node_key: AgentName,
        node_data: dict,
        is_json: bool,
        finished: bool,
        expected_fields: list[str] | None = None,
        tool_override: tuple[str, dict] | None = None,
    ):
        """Unified response generator ensures all required fields are present."""
        logger.info("mock_dspy_lm_generate", node=node_key, finished=finished)

        thought = node_data.get("thought", "Task in progress.")
        reasoning = node_data.get("reasoning", "Verified all requirements.")
        expected_fields = expected_fields or []
        legacy_next_fields = any(
            f in expected_fields
            for f in ("next_thought", "next_tool_name", "next_tool_args")
        )

        tool_calls = node_data.get("tool_calls", [])
        # WP10: Support explicit tool calls in scenarios
        # We use call_count to track which tool we are on
        tool_progress = self._tool_progress.get(node_key, 0)
        tool_name = None
        tool_args = {}

        if not finished:
            if tool_override:
                tool_name, tool_args = tool_override
            else:
                # WP10: Support explicit tool calls in scenarios (legacy mode)
                tool_progress = self._tool_progress.get(node_key, 0)
                tool_calls = node_data.get("tool_calls", [])

                if tool_progress < len(tool_calls) and len(tool_calls) > 0:
                    # Still have explicit tools to call.
                    tc = tool_calls[tool_progress]
                    thought = tc.get("thought", thought)
                    tool_name = tc.get("name")
                    tool_args = tc.get("input", {})

        # Base schema for DSPy JSONAdapter
        resp = {
            "thought": thought,
            "reasoning": reasoning,
            "finished": finished,
        }

        # Keep node-signature fields present even during JSON tool turns.
        # Some DSPy predictor paths still expect signature outputs while a tool
        # action is being selected, and they tolerate extra fields better than
        # missing required ones.
        if node_key in PLANNER_AGENTS:
            default_plan = {
                "theme": "benchmark_test",
                "target_object_properties": {},
                "environment_perturbations": {},
                "difficulty_score": 0.5,
                "reasoning": "Default mock benchmark plan.",
            }
            resp["plan"] = node_data.get("plan", default_plan)
            resp["summary"] = node_data.get("summary", "Plan generated.")
            if "plan" in node_data and isinstance(node_data["plan"], dict):
                resp["plan"] = node_data["plan"]
        elif node_key in REVIEWER_AGENTS:
            resp["review"] = node_data.get(
                "review",
                {
                    "decision": "APPROVED",
                    "reason": "Verified.",
                    "required_fixes": [],
                },
            )
        elif node_key in CODER_AGENTS:
            resp["journal"] = node_data.get("journal", "Work completed.")
        elif node_key == AgentName.JOURNALLING_AGENT:
            resp["summarized_journal"] = node_data.get(
                "summarized_journal", "Journal summary."
            )
        elif node_key == AgentName.SKILL_AGENT:
            resp["summary"] = node_data.get("summary", "Skills identified.")
            resp["journal"] = node_data.get("journal", "Learning complete.")
        elif node_key == AgentName.COTS_SEARCH:
            resp["search_summary"] = node_data.get("search_summary", "Search complete.")
        # Legacy ReAct (3.1.3) internal predictor fields.
        # For JSON mode we keep both legacy and modern fields to avoid brittle
        # parser-mode mismatches across DSPy predictor variants.
        legacy_resp = {
            "next_thought": thought,
            "next_tool_name": (
                tool_name
                if (isinstance(tool_name, str) and tool_name.strip())
                else "finish"
            ),
            "next_tool_args": tool_args or {},
        }
        if legacy_next_fields:
            lines = []
            for field in expected_fields:
                if field not in legacy_resp:
                    continue
                val = legacy_resp[field]
                if isinstance(val, (dict, list)):
                    val = json.dumps(val)
                lines.append(f"[[ ## {field} ## ]]\n{val!s}")
            if lines:
                return ["\n\n".join(lines)]
            return [json.dumps(legacy_resp)]

        # Structured tool-turn output for thought/tool_name/tool_args predictors.
        tool_fields = any(
            f in expected_fields for f in ("thought", "tool_name", "tool_args")
        )
        if not finished and tool_name and tool_fields and not legacy_next_fields:
            tool_resp = {
                **resp,
                "thought": thought,
                "tool_name": tool_name,
                "tool_args": tool_args or {},
            }
            lines = []
            for field in expected_fields:
                if field not in tool_resp:
                    continue
                val = tool_resp[field]
                if isinstance(val, (dict, list)):
                    val = json.dumps(val)
                lines.append(f"[[ ## {field} ## ]]\n{val!s}")
            if lines:
                return ["\n\n".join(lines)]
            return [json.dumps(tool_resp)]

        # Tool turns are emitted in plain ReAct format for native tool-call prompts.
        if not finished and tool_name:
            # Prefer structured output for tool turns to keep DSPy adapters stable
            # across prompt-format variations.
            tool_turn_resp = {
                **resp,
                "thought": thought,
                "tool_name": tool_name,
                "tool_args": tool_args or {},
                **legacy_resp,
            }
            return [json.dumps(tool_turn_resp)]

        if is_json:
            if expected_fields:
                # Prefer field-block output when DSPy has explicit expected fields.
                # Raw JSON here is brittle with ChatAdapter in integration runs.
                pass
            else:
                # WP10: Do NOT filter JSON responses. dspy adapters are very sensitive to missing fields
                # but generally ignore extra ones. Filtering often causes AdapterParseError.
                merged = {**resp, **legacy_resp}
                logger.info("mock_dspy_returning_json", json=merged)
                return [json.dumps(merged)]

        # Fallback for field-based format (common in non-JSON dspy.ReAct)
        if expected_fields:
            # Ensure signature-defined output fields are also included
            # ReAct sometimes expects them even in intermediate turns
            sig_fields = {
                AgentName.ENGINEER_PLANNER: ["thought", "reasoning", "plan", "summary"],
                AgentName.BENCHMARK_PLANNER: [
                    "thought",
                    "reasoning",
                    "plan",
                    "summary",
                ],
                AgentName.ENGINEER_CODER: ["thought", "journal"],
                AgentName.BENCHMARK_CODER: ["thought", "journal"],
                AgentName.ENGINEER_PLAN_REVIEWER: ["thought", "review"],
                AgentName.BENCHMARK_PLAN_REVIEWER: ["thought", "review"],
                AgentName.BENCHMARK_REVIEWER: ["thought", "review"],
                AgentName.ENGINEER_EXECUTION_REVIEWER: ["thought", "review"],
                AgentName.JOURNALLING_AGENT: ["thought", "summarized_journal"],
                AgentName.SKILL_AGENT: ["thought", "summary", "journal"],
                AgentName.COTS_SEARCH: ["thought", "search_summary"],
            }.get(node_key, [])

            all_fields = list(dict.fromkeys(expected_fields + sig_fields))

            if finished and "finished" not in all_fields:
                all_fields.append("finished")

            # WP10: Force plan inclusion for planner nodes to ensure state transitions work
            if node_key in PLANNER_AGENTS and "plan" not in all_fields:
                all_fields.append("plan")

            lines = []
            for field in all_fields:
                val = resp.get(field)
                if val is None:
                    # Provide default values for missing expected fields to satisfy parser
                    if field == "plan" and node_key in PLANNER_AGENTS:
                        val = node_data.get("plan", {})
                    elif field == "review" and node_key in REVIEWER_AGENTS:
                        val = node_data.get("review", {})
                    else:
                        val = "None"

                if isinstance(val, bool):
                    val = str(val).lower()
                elif field == "plan" and node_key in PLANNER_AGENTS:
                    # WP10: Always use JSON for the plan object in planner nodes
                    val = json.dumps(val)
                elif isinstance(val, (dict, list)):
                    val = json.dumps(val)

                # TypedPredictor expects [[ ## field ## ]] followed by value on NEXT line
                lines.append(f"[[ ## {field} ## ]]\n{val!s}")

            result = "\n\n".join(lines)
            logger.info("mock_dspy_returning_fields", text=result)
            return [result]

        # Fallback for plain text (rare in our ReAct setups)
        if node_key in REVIEWER_AGENTS:
            return ["Review Result: approved\nReasoning: Approved."]
        return [
            f"Thought: {thought}\nReasoning: {reasoning}\nFinal Answer: Task complete."
        ]

    @staticmethod
    def _normalize_text_list(value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [value]
        if isinstance(value, list):
            return [str(v) for v in value]
        return [str(value)]

    def _assert_text_expectations(
        self,
        *,
        context: str,
        text: str,
        contains: list[str],
        not_contains: list[str],
    ) -> None:
        for token in contains:
            if token not in text:
                raise AssertionError(
                    f"{context}: expected token not found in LM input/trajectory: {token!r}"
                )
        for token in not_contains:
            if token in text:
                raise AssertionError(
                    f"{context}: unexpected token found in LM input/trajectory: {token!r}"
                )

    def _validate_expected_llm_inputs(
        self,
        *,
        node_key: str,
        node_data: dict[str, Any],
        full_text: str,
        call_index: int,
    ) -> None:
        expected = node_data.get("expected_llm_inputs")
        if not expected:
            return

        if isinstance(expected, dict):
            contains = self._normalize_text_list(expected.get("contains"))
            not_contains = self._normalize_text_list(expected.get("not_contains"))
            self._assert_text_expectations(
                context=f"{node_key} call {call_index} expected_llm_inputs",
                text=full_text,
                contains=contains,
                not_contains=not_contains,
            )
            for rule in expected.get("per_call", []):
                if int(rule.get("call_index", -1)) != call_index:
                    continue
                self._assert_text_expectations(
                    context=f"{node_key} call {call_index} expected_llm_inputs.per_call",
                    text=full_text,
                    contains=self._normalize_text_list(rule.get("contains")),
                    not_contains=self._normalize_text_list(rule.get("not_contains")),
                )
            return

        if isinstance(expected, list):
            # If entries are strings, all are required for every call.
            if all(isinstance(item, str) for item in expected):
                self._assert_text_expectations(
                    context=f"{node_key} call {call_index} expected_llm_inputs",
                    text=full_text,
                    contains=[str(item) for item in expected],
                    not_contains=[],
                )
                return

            for rule in expected:
                if not isinstance(rule, dict):
                    continue
                expected_call = rule.get("call_index")
                if expected_call is not None and int(expected_call) != call_index:
                    continue
                self._assert_text_expectations(
                    context=f"{node_key} call {call_index} expected_llm_inputs",
                    text=full_text,
                    contains=self._normalize_text_list(rule.get("contains")),
                    not_contains=self._normalize_text_list(rule.get("not_contains")),
                )

    def _extract_indexed_fields(
        self, full_text: str, field_prefix: str
    ) -> dict[int, str]:
        out: dict[int, str] = {}

        marker_pattern = re.compile(
            rf"\[\[\s*##\s*{re.escape(field_prefix)}_(\d+)\s*##\s*\]\]\s*(.*?)(?=\n\s*\[\[\s*##|\Z)",
            re.IGNORECASE | re.DOTALL,
        )
        for match in marker_pattern.finditer(full_text):
            idx = int(match.group(1))
            value = match.group(2).strip()
            out[idx] = value

        # Fallback parser for non-marker prompt formats.
        kv_pattern = re.compile(
            rf"[\"']?{re.escape(field_prefix)}_(\d+)[\"']?\s*[:=]\s*([^\n]+)",
            re.IGNORECASE,
        )
        for match in kv_pattern.finditer(full_text):
            idx = int(match.group(1))
            out.setdefault(idx, match.group(2).strip().strip(","))

        return out

    def _validate_expected_tool_calls(
        self, *, node_key: str, node_data: dict[str, Any], full_text: str
    ) -> None:
        expected_calls = node_data.get("expected_tool_calls")
        if not expected_calls:
            return

        observed_names = self._extract_indexed_fields(full_text, "tool_name")
        observed_args = self._extract_indexed_fields(full_text, "tool_args")
        max_observed_idx = max(observed_names.keys(), default=-1)

        for idx in range(min(len(expected_calls), max_observed_idx + 1)):
            rule = expected_calls[idx]
            if not isinstance(rule, dict):
                continue

            expected_name = rule.get("name")
            observed_name = observed_names.get(idx)
            if expected_name and observed_name and expected_name != observed_name:
                raise AssertionError(
                    f"{node_key} tool {idx}: expected name {expected_name!r}, got {observed_name!r}"
                )

            args_text = observed_args.get(idx, "")
            self._assert_text_expectations(
                context=f"{node_key} tool {idx} expected_tool_calls",
                text=args_text,
                contains=self._normalize_text_list(rule.get("args_contains")),
                not_contains=self._normalize_text_list(rule.get("args_not_contains")),
            )

    def _validate_expected_tool_outputs(
        self, *, node_key: str, node_data: dict[str, Any], full_text: str
    ) -> None:
        expected_outputs = node_data.get("expected_tool_outputs")
        if not expected_outputs:
            return

        observed_outputs = self._extract_indexed_fields(full_text, "observation")
        max_observed_idx = max(observed_outputs.keys(), default=-1)

        for idx in range(min(len(expected_outputs), max_observed_idx + 1)):
            rule = expected_outputs[idx]
            if isinstance(rule, str):
                contains = [rule]
                not_contains: list[str] = []
            elif isinstance(rule, dict):
                contains = self._normalize_text_list(rule.get("contains"))
                not_contains = self._normalize_text_list(rule.get("not_contains"))
            else:
                continue

            self._assert_text_expectations(
                context=f"{node_key} observation {idx} expected_tool_outputs",
                text=observed_outputs.get(idx, ""),
                contains=contains,
                not_contains=not_contains,
            )
