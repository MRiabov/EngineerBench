from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

from shared.agent_templates import load_template_text

REPO_ROOT = Path(__file__).resolve().parents[2]
INTEGRATION_SCENARIO_ID_PATTERN = re.compile(r"^INT-\d{3}$")
INTEGRATION_MOCK_RESPONSES_DIR = REPO_ROOT / "tests" / "integration" / "mock_responses"


class TranscriptStepSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    thought: str | None = None
    tool_name: str | None = None
    tool_args: dict[str, Any] | None = None
    expected_observation: str | None = None
    finished: bool | None = None
    summary: str | None = None
    journal: str | None = None
    review: dict[str, Any] | None = None
    plan: dict[str, Any] | None = None

    @model_validator(mode="after")
    def validate_step(self) -> TranscriptStepSpec:
        has_tool = self.tool_name is not None
        is_finished = bool(self.finished)
        if has_tool and is_finished:
            raise ValueError(
                "Transcript step cannot define both tool_name and finished."
            )
        if not has_tool and not is_finished:
            raise ValueError(
                "Transcript step must define either tool_name or finished."
            )
        return self


class TranscriptNodeSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node: str
    steps: list[TranscriptStepSpec]


class TranscriptScenarioSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    transcript: list[TranscriptNodeSpec]


def _expand_content_file_refs(value: Any, *, base_dir: Path) -> Any:
    if isinstance(value, list):
        return [_expand_content_file_refs(item, base_dir=base_dir) for item in value]

    if not isinstance(value, dict):
        return value

    expanded = {
        key: _expand_content_file_refs(item, base_dir=base_dir)
        for key, item in value.items()
        if key not in {"content_file", "template_file"}
    }
    content_file = value.get("content_file")
    template_file = value.get("template_file")
    if content_file is not None and template_file is not None:
        raise ValueError(
            "Scenario entry may not define both 'content_file' and 'template_file'."
        )

    if content_file is None and template_file is None:
        return expanded

    if "content" in expanded:
        raise ValueError("Scenario entry may not define both 'content' and a file ref.")

    if content_file is not None:
        content_path = (base_dir / str(content_file)).resolve()
        try:
            content_path.relative_to(base_dir.resolve())
        except ValueError as exc:
            raise ValueError(
                f"content_file path escapes scenario directory: {content_file}"
            ) from exc

        if not content_path.is_file():
            raise FileNotFoundError(
                f"content_file not found for scenario fixture: {content_path}"
            )

        expanded["content"] = content_path.read_text(encoding="utf-8")
    else:
        expanded["content"] = load_template_text(str(template_file))

    return expanded


def _validate_scenarios(
    scenarios: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    for scenario_id, scenario in scenarios.items():
        if INTEGRATION_SCENARIO_ID_PATTERN.fullmatch(scenario_id) is None:
            raise ValueError(
                "Invalid integration mock scenario ID found. Expected strict "
                f"INT-### IDs only: {scenario_id}"
            )
        transcript = scenario.get("transcript")
        if transcript is None:
            continue
        try:
            TranscriptScenarioSpec.model_validate({"transcript": transcript})
        except ValidationError as exc:
            raise ValueError(
                f"Invalid transcript schema in integration mock scenario "
                f"'{scenario_id}': {exc}"
            ) from exc
    return scenarios


def _load_from_directory(root: Path) -> dict[str, dict[str, Any]]:
    if not root.exists():
        raise FileNotFoundError(
            f"Integration mock responses directory not found: {root}"
        )
    if not root.is_dir():
        raise ValueError(f"Integration mock responses path must be a directory: {root}")

    scenarios: dict[str, dict[str, Any]] = {}
    seen_ids: dict[str, Path] = {}
    scenario_files = sorted(root.glob("*.yaml")) + sorted(root.glob("*.yml"))
    if not scenario_files:
        raise ValueError(
            f"No scenario files found in integration mock responses directory: {root}"
        )

    for scenario_file in scenario_files:
        scenario_id = scenario_file.stem
        if INTEGRATION_SCENARIO_ID_PATTERN.fullmatch(scenario_id) is None:
            raise ValueError(
                "Invalid integration mock scenario filename. Expected strict "
                f"INT-###.yaml naming only: {scenario_file.name}"
            )
        if scenario_id in seen_ids:
            raise ValueError(
                f"Duplicate integration mock scenario ID '{scenario_id}' in "
                f"{seen_ids[scenario_id]} and {scenario_file}"
            )
        raw_scenario = yaml.safe_load(scenario_file.read_text(encoding="utf-8")) or {}
        if not isinstance(raw_scenario, dict):
            raise ValueError(
                f"Invalid scenario file {scenario_file}: expected mapping at root."
            )
        scenarios[scenario_id] = _expand_content_file_refs(
            raw_scenario,
            base_dir=scenario_file.parent,
        )
        seen_ids[scenario_id] = scenario_file

    return _validate_scenarios(scenarios)


def load_integration_mock_scenarios(
    root: Path | None = None,
) -> dict[str, dict[str, Any]]:
    source = INTEGRATION_MOCK_RESPONSES_DIR if root is None else root
    if not source.exists():
        raise FileNotFoundError(
            f"Integration mock responses directory not found: {source}"
        )
    if not source.is_dir():
        raise ValueError(
            f"Integration mock responses path must be a directory: {source}"
        )
    return _load_from_directory(source)
