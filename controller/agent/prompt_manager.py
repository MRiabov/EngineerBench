from enum import StrEnum
from pathlib import Path
from typing import Any

import dspy
import structlog
from pydantic import BaseModel, ConfigDict, Field

from shared.agents.config import load_agents_config
from shared.enums import AgentName
from shared.skills import build_skill_catalog_lines

from ..prompts import load_prompts

logger = structlog.get_logger(__name__)


class PromptBackendFamily(StrEnum):
    API_BASED = "api_based"
    CLI_BASED = "cli_based"


class PromptCliAppendices(BaseModel):
    model_config = ConfigDict(extra="allow")

    shared: str = ""
    providers: dict[str, str] = Field(default_factory=dict)


class PromptAppendices(BaseModel):
    model_config = ConfigDict(extra="allow")

    shared: str = ""
    bug_reporting: str = ""
    drafting: dict[str, str] = Field(default_factory=dict)
    backend: dict[str, str] = Field(default_factory=dict)
    cli: PromptCliAppendices = Field(default_factory=PromptCliAppendices)


class PromptSourceConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    role_prompts: dict[str, str] = Field(default_factory=dict)
    appendices: PromptAppendices = Field(default_factory=PromptAppendices)


class PromptManager:
    """Manager for unified prompt assembly across backends."""

    _ROLE_KEY_MAP: dict[str, str] = {
        AgentName.BENCHMARK_PLANNER.value: "benchmark_planner",
        AgentName.BENCHMARK_PLAN_REVIEWER.value: "benchmark_plan_reviewer",
        AgentName.BENCHMARK_CODER.value: "benchmark_coder",
        AgentName.BENCHMARK_REVIEWER.value: "benchmark_reviewer",
        AgentName.ENGINEER_PLANNER.value: "engineer_planner",
        AgentName.ENGINEER_PLAN_REVIEWER.value: "engineer_plan_reviewer",
        AgentName.ENGINEER_CODER.value: "engineer_coder",
        AgentName.ENGINEER_EXECUTION_REVIEWER.value: "engineer_execution_reviewer",
        AgentName.SKILL_AGENT.value: "skill_agent",
        AgentName.JOURNALLING_AGENT.value: "journalling_agent",
    }

    def __init__(self) -> None:
        self._prompt_source = PromptSourceConfig.model_validate(load_prompts())
        try:
            self._agents_config = load_agents_config()
        except Exception:
            self._agents_config = None

    def _bug_reports_enabled(self) -> bool:
        if self._agents_config is None:
            return False
        try:
            return bool(self._agents_config.bug_reports.enabled)
        except Exception:
            return False

    def _resolve_role_key(self, template_name: str | AgentName) -> str:
        if isinstance(template_name, AgentName):
            key = self._ROLE_KEY_MAP.get(template_name.value, template_name.value)
        else:
            key = self._ROLE_KEY_MAP.get(str(template_name), str(template_name))
        if key in self._prompt_source.role_prompts:
            return key
        if "default" in self._prompt_source.role_prompts:
            return "default"
        raise ValueError(f"Template '{template_name}' not found")

    def render(
        self,
        template_name: str | AgentName,
        *,
        backend_family: str | PromptBackendFamily = PromptBackendFamily.API_BASED,
        cli_provider_name: str | None = None,
        runtime_context: str | None = None,
    ) -> str:
        """Render a prompt with the shared base source model and runtime context."""

        role_key = self._resolve_role_key(template_name)
        role_prompt = self._prompt_source.role_prompts[role_key].strip()

        backend_key = (
            backend_family.value
            if isinstance(backend_family, PromptBackendFamily)
            else str(backend_family)
        )
        backend_appendix = self._prompt_source.appendices.backend.get(backend_key)
        if backend_appendix is None:
            raise ValueError(f"Prompt backend family '{backend_family}' not found")

        prompt_sections = [
            role_prompt,
        ]
        shared_appendix = self._prompt_source.appendices.shared.strip()
        if shared_appendix:
            prompt_sections.append(shared_appendix)
        if self._bug_reports_enabled():
            bug_reporting_appendix = (
                self._prompt_source.appendices.bug_reporting.strip()
            )
            if not bug_reporting_appendix:
                raise ValueError(
                    "Bug-report mode is enabled, but config/prompts.yaml is missing appendices.bug_reporting"
                )
            prompt_sections.append(bug_reporting_appendix)
        prompt_sections.append(backend_appendix.strip())
        if backend_key == PromptBackendFamily.CLI_BASED.value:
            cli_appendices = self._prompt_source.appendices.cli
            shared_cli_appendix = cli_appendices.shared.strip()
            provider_appendix = ""
            if cli_provider_name:
                provider_key = cli_provider_name.strip().lower()
                raw_provider_appendix = cli_appendices.providers.get(provider_key)
                if raw_provider_appendix:
                    provider_appendix = raw_provider_appendix.strip()
            if shared_cli_appendix:
                prompt_sections.append(shared_cli_appendix)
            if provider_appendix:
                prompt_sections.append(provider_appendix)
        if runtime_context and runtime_context.strip():
            prompt_sections.append(runtime_context.strip())
        # CLI-backed runs already get the skill files through the workspace
        # contract, so they do not need the extra catalog text in the prompt.
        if backend_key != PromptBackendFamily.CLI_BASED.value:
            skill_catalog = "\n".join(build_skill_catalog_lines()).strip()
            if skill_catalog:
                prompt_sections.append(skill_catalog)
        return (
            "\n\n".join(section for section in prompt_sections if section).rstrip()
            + "\n"
        )

    def get_prompt_value(self, key: str) -> Any:
        """Return a raw value from config/prompts.yaml using dot-separated keys."""
        data = load_prompts()
        value: Any = data
        for segment in key.split("."):
            if isinstance(value, dict) and segment in value:
                value = value[segment]
            else:
                raise KeyError(f"Prompt key '{key}' not found in config.")
        return value

    def load_compiled_program(
        self, agent_name: AgentName, program: dspy.Module
    ) -> dspy.Module:
        """
        Loads a compiled DSPy program from config/compiled_prompts/ if it exists.
        """
        prompt_path = Path("config/compiled_prompts") / f"{agent_name.value}.json"

        if prompt_path.exists():
            try:
                program.load(str(prompt_path))
                logger.info(
                    "compiled_prompt_loaded",
                    agent_name=agent_name,
                    path=str(prompt_path),
                )
            except Exception as e:
                logger.error(
                    "compiled_prompt_load_failed",
                    agent_name=agent_name,
                    error=str(e),
                    session_id="system",
                )
        else:
            logger.debug("no_compiled_prompt_found", agent_name=agent_name)

        return program
