import asyncio
from pathlib import Path
from typing import Any

import structlog
from pydantic import BaseModel, Field

from controller.clients.worker import WorkerClient
from shared.enums import AgentName, ReviewDecision
from shared.eval_artifacts import plan_artifacts_for_agent
from shared.observability.schemas import ObservabilityEventType

logger = structlog.get_logger(__name__)


class PredictionMetrics(BaseModel):
    """
    Formalized metrics for agent performance prediction.
    Aggregates signals from worker events for reward calculation.
    """

    # General Execution
    script_compiled: bool = False
    cad_geometry_valid: bool = False
    simulation_ran: bool = False
    simulation_success: bool = False
    simulation_stable: bool = True
    error: str | None = None

    # Engineering / CAD
    manufacturability_valid: bool = False
    parts_within_build_zone: bool = False
    actual_cost: float = 0.0
    actual_weight: float = 0.0
    min_distance_to_goal: float = 1.0
    initial_distance: float = 1.0

    # Planning
    plan_artifacts_present: bool = False
    yaml_schema_valid: bool = True
    estimated_cost: float = 0.0
    estimated_weight: float = 0.0
    cots_ids_valid: bool = True
    geometry_consistent: bool = True
    mechanism_fits_build_zone: bool = True
    engineer_implemented_successfully: bool = False

    # Reviewing
    review_artifacts_complete: bool = False
    reviewer_accepted: bool = False
    reviewer_decision: str | None = None
    reviewer_feedback: str | None = None
    review_actionable: bool = True
    decision_correct: bool = False
    feedback_response_score: float = 0.0
    bad_feedback_resistance_score: float = 0.0
    checklist: dict[str, Any] = Field(default_factory=dict)

    # COTS Search
    n_queries: int = 0
    n_valid_candidates: int = 0
    n_returned_candidates: int = 0
    candidate_adopted: bool = False

    # Skills
    skill_file_valid: bool = False
    skill_adopted: bool = False
    delta_success_rate: float = 0.0

    # Benchmark specific
    benchmark_constraints_satisfied: bool = True


class WorkerInterpreter:
    """
    A DSPy CodeInterpreter that executes code on the remote worker.
    Uses the project's 'well formed remote execution environment'.
    """

    def __init__(
        self,
        worker_client: WorkerClient,
        session_id: str,
        episode_id: str | None = None,
    ):
        self.worker_client = worker_client
        self.session_id = session_id
        self.episode_id = episode_id

    def __call__(self, code: str) -> str:
        """Execute code on the worker and return the output."""
        logger.debug("worker_interpreter_execute_start", code_len=len(code))

        # DSPy ReAct expects a synchronous call.
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        if loop.is_running():
            try:
                import nest_asyncio

                nest_asyncio.apply(loop)
            except Exception as e:
                logger.warning(
                    "nest_asyncio_apply_failed",
                    error=str(e),
                    loop_type=type(loop).__name__,
                )

        result = loop.run_until_complete(self._execute_remote(code))

        output = f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        if result.exit_code != 0:
            output += f"\nExit Code: {result.exit_code}"

        logger.debug("worker_interpreter_execute_complete", exit_code=result.exit_code)
        return output

    async def _execute_remote(self, code: str):
        """Internal async execution call."""
        # T025: Add timeout to prevent thread leak in BaseNode (Issue 1)
        # 1000s matches the expanded execution budget for long-running tasks.
        return await asyncio.wait_for(
            self.worker_client.execute_command(code, episode_id=self.episode_id),
            timeout=1000.0,
        )

    def shutdown(self):
        """Cleanup if needed."""
        pass


def evaluate_formula(formula: str, context: dict) -> float:
    """Safely eval a math formula with a provided context."""
    try:
        allowed_names = {
            "max": max,
            "min": min,
            "abs": abs,
            "pow": pow,
            "round": round,
            "n_valid_candidates": context.get("n_valid_candidates", 0),
            "n_returned_candidates": context.get("n_returned_candidates", 1),
            "n_queries": context.get("n_queries", 0),
            "delta_success_rate": context.get("delta_success_rate", 0.0),
        }
        allowed_names.update(context)
        return float(eval(formula, {"__builtins__": {}}, allowed_names))
    except Exception as e:
        logger.warning("formula_eval_failed", formula=formula, error=str(e))
        return 0.0


def cad_simulation_metric(
    gold, prediction, trace=None, pred_name=None, pred_trace=None
) -> Any:
    """
    Unified DSPy metric for CAD simulation performance.
    Returns a dspy.Prediction with 'score' and 'feedback' for GEPA.
    """
    from dspy import Prediction

    from controller.agent.reward import load_reward_config

    agent_name = getattr(gold, "agent_name", AgentName.ENGINEER_CODER)
    full_cfg = load_reward_config()

    # Find the agent config in the hierarchy
    cfg = None
    for category in ["engineer", "benchmark", "shared"]:
        cat_cfg = getattr(full_cfg, category, {})
        if agent_name in cat_cfg:
            cfg = cat_cfg[agent_name]
            break

    if not cfg:
        logger.warning("reward_config_agent_not_found", agent_name=agent_name)
        return Prediction(
            score=0.02, feedback=f"Agent '{agent_name}' not found in reward_config."
        )

    score = 0.0
    feedback_parts = []
    context = {"prediction": prediction, "gold": gold}

    def resolve_metric_value(name: str, aliases: list[str]) -> Any:
        for candidate in [name, *aliases]:
            if hasattr(prediction, candidate):
                return getattr(prediction, candidate)
        return None

    def extract_checklist_value(obj: Any, key: str) -> Any:
        checklist = getattr(obj, "checklist", None)
        if isinstance(checklist, dict) and key in checklist:
            return checklist[key]
        attr_name = f"checklist_{key}"
        if hasattr(obj, attr_name):
            return getattr(obj, attr_name)
        return None

    def normalize_checklist_value(value: Any) -> float | None:
        if value is None:
            return None
        if isinstance(value, bool):
            return 1.0 if value else 0.0
        if isinstance(value, int | float):
            return max(0.0, min(1.0, float(value)))
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized == "pass":
                return 1.0
            if normalized == "fail":
                return 0.0
            if normalized in {"not_applicable", "n/a", "na"}:
                return 1.0
        return None

    def inject_scalar_attrs(obj: Any) -> None:
        if obj is None:
            return
        for attr_name in dir(obj):
            if attr_name.startswith("_") or attr_name in context:
                continue
            try:
                value = getattr(obj, attr_name)
            except Exception:
                continue
            if callable(value):
                continue
            if isinstance(value, bool | int | float):
                context[attr_name] = value

    # Map attributes for formula evaluation
    mapping = {
        "actual_cost": ["actual_cost"],
        "actual_weight": ["actual_weight"],
        "min_distance_achieved": ["min_distance_to_goal", "min_distance_achieved"],
        "initial_distance": ["initial_distance"],
        "estimated_cost": ["estimated_cost"],
        "estimated_weight": ["estimated_weight"],
        "total_power": ["total_power"],
        "n_valid_candidates": ["n_valid_candidates"],
        "n_returned_candidates": ["n_returned_candidates"],
        "n_queries": ["n_queries"],
        "delta_success_rate": ["delta_success_rate"],
    }

    for obj in [prediction, gold]:
        inject_scalar_attrs(obj)
        for target, sources in mapping.items():
            for src in sources:
                if hasattr(obj, src):
                    context[target] = getattr(obj, src)
                    break
        if hasattr(obj, "objectives"):
            obj_yaml = obj.objectives
            # Map from BenchmarkDefinition nested structure
            if hasattr(obj_yaml, "constraints"):
                max_unit_cost = obj_yaml.constraints.max_unit_cost
                max_weight_g = obj_yaml.constraints.max_weight_g
                if max_unit_cost is not None:
                    context["max_unit_cost"] = max_unit_cost
                if max_weight_g is not None:
                    context["max_weight_g"] = max_weight_g
                    # Fallback for legacy formulas
                    context["max_weight"] = max_weight_g

    error_msg = getattr(prediction, "error", None)

    for milestone_name, m in cfg.all_milestones().items():
        m_score = 0.0
        details = ""

        if milestone_name.startswith("checklist."):
            checklist_key = milestone_name.split(".", 1)[1]
            pred_value = normalize_checklist_value(
                extract_checklist_value(prediction, checklist_key)
            )
            gold_value = normalize_checklist_value(
                extract_checklist_value(gold, checklist_key)
            )
            if gold_value is not None:
                m_score = (
                    1.0 if pred_value is not None and pred_value == gold_value else 0.0
                )
                details = (
                    f"{checklist_key} matched seeded checklist."
                    if m_score == 1.0
                    else f"{checklist_key} mismatched seeded checklist."
                )
            else:
                m_score = pred_value if pred_value is not None else 0.0
                details = f"{checklist_key} checklist result: {m_score:.2f}"

            score += m.weight * m_score
            feedback_parts.append(details)
            continue

        aliases = {
            "script_compiles": ["script_compiled", "compiled"],
            "simulation_result": ["simulation_success", "simulation_ran"],
            "cad_geometry_valid": ["geometry_valid", "cad_geometry_valid"],
            "reviewer_accepted": ["accepted", "reviewer_accepted"],
            "engineer_implemented_successfully": [
                "engineer_implemented_successfully",
                "simulation_success",
            ],
            "manufacturability_valid": ["manufacturability_valid"],
            "parts_within_build_zone": ["parts_within_build_zone"],
        }
        candidates = aliases.get(milestone_name, [])
        raw_value = resolve_metric_value(milestone_name, candidates)
        is_triggered = bool(raw_value)

        if milestone_name == "script_compiles":
            if not is_triggered:
                fb = m.failure_feedback or "Script did not compile."
                if error_msg:
                    fb += f" Error: {error_msg}"
                return Prediction(score=m.minimum_score or 0.02, feedback=fb)
            m_score = 1.0
            details = m.success_feedback or "Script compiled successfully."
        elif milestone_name == "cad_geometry_valid":
            if not is_triggered:
                fb = m.failure_feedback or "CAD geometry is invalid or missing."
                return Prediction(score=score, feedback=fb)
            m_score = 1.0
            details = m.success_feedback or "CAD geometry is valid."
        elif m.binary:
            m_score = 1.0 if is_triggered else 0.0
            details = (
                (m.success_feedback if is_triggered else m.failure_feedback)
                or f"{milestone_name.replace('_', ' ').capitalize()} status: {is_triggered}"
            )
        elif m.partial:
            # Handle partial credit and select feedback
            is_sim_ran = any(
                getattr(prediction, c, False)
                for c in ["simulation_ran", "simulation_success"]
            )
            if milestone_name == "simulation_result" and not is_sim_ran:
                m_score = 0.0
                details = m.failure_feedback or "Simulation did not run."
            elif milestone_name in ["simulation_result", "decision_correct"]:
                if getattr(prediction, "simulation_success", False) or getattr(
                    prediction, "decision_correct", False
                ):
                    m_score = 1.0
                    details = m.success_feedback or "Full success achieved."
                elif m.failure_formula:
                    m_score = evaluate_formula(m.failure_formula, context) / m.weight
                    details = (
                        m.failure_feedback or "Partial credit awarded."
                    ) + f" (Progress: {m_score:.2f})"
            else:
                f = m.penalty_formula or m.formula
                if f:
                    m_score = evaluate_formula(f, context)
                    details = (
                        m.success_feedback if m_score >= 0.9 else m.failure_feedback
                    ) or f"{milestone_name} score: {m_score:.2f}"
                elif isinstance(raw_value, int | float) and not isinstance(
                    raw_value, bool
                ):
                    m_score = max(0.0, min(1.0, float(raw_value)))
                    details = (
                        m.success_feedback if m_score >= 0.9 else m.failure_feedback
                    ) or f"{milestone_name} score: {m_score:.2f}"
                else:
                    m_score = 1.0 if is_triggered else 0.0
                    details = (
                        m.success_feedback if is_triggered else m.failure_feedback
                    ) or f"{milestone_name} result: {is_triggered}"
        else:
            m_score = 1.0 if is_triggered else 0.0
            details = (
                m.success_feedback if is_triggered else m.failure_feedback
            ) or f"{milestone_name} result: {is_triggered}"

        score += m.weight * m_score
        feedback_parts.append(details)

    final_fb = " | ".join(filter(None, feedback_parts))

    # Append specific reviewer feedback if available and not already covered
    rev_fb = getattr(prediction, "reviewer_feedback", None)
    if rev_fb and "Reviewer Rejection" not in (error_msg or ""):
        final_fb += f" | Reviewer Feedback: {rev_fb}"

    if error_msg:
        final_fb = f"Error: {error_msg} | {final_fb}"

    return Prediction(score=min(score, 1.0), feedback=final_fb)


def map_events_to_prediction(
    events: list[dict | Any],
    _objectives: Any = None,
    *,
    agent_name: AgentName | None = None,
) -> PredictionMetrics:
    """
    Translates worker events into a structured PredictionMetrics model.
    Supports all agents (Planners, Engineers, Reviewers, COTS, Skills).
    """
    metrics = PredictionMetrics()

    # Tracking for artifact presence
    planned_files = set()
    required_planner_files = (
        set(plan_artifacts_for_agent(agent_name)) if agent_name is not None else set()
    )

    for event in events:
        # Support both 'event_type' (BaseEvent) and 'type' (legacy/other)
        if isinstance(event, dict):
            etype = event.get("event_type") or event.get("type")
            data = event.get("data", event)
        else:
            etype = getattr(event, "event_type", None)
            data = event

        if not etype:
            continue

        # 1. Filesystem & Artifacts
        if etype == ObservabilityEventType.TOOL_INVOCATION:
            tool_name = (
                data.get("tool_name", "")
                if isinstance(data, dict)
                else getattr(data, "tool_name", "")
            )
            arguments = (
                data.get("arguments", {})
                if isinstance(data, dict)
                else getattr(data, "arguments", {})
            )
            if tool_name == "write_file":
                path = str(arguments.get("path", ""))
                if any(path.endswith(f) for f in required_planner_files):
                    planned_files.add(Path(path).name)
                if "review" in path.lower() and path.endswith(".yaml"):
                    metrics.review_artifacts_complete = True

        # 2. Planning & Logic
        if (
            required_planner_files
            and etype
            in [
                ObservabilityEventType.PLAN_SUBMISSION_ENGINEER,
                ObservabilityEventType.PLAN_SUBMISSION_BENCHMARK,
            ]
            and required_planner_files.issubset(planned_files)
        ):
            metrics.plan_artifacts_present = True

        # 3. Manufacturability & Pricing
        if etype == ObservabilityEventType.MANUFACTURABILITY_CHECK:
            result = (
                data.get("result")
                if isinstance(data, dict)
                else getattr(data, "result", False)
            )
            if result:
                metrics.manufacturability_valid = True
                metrics.parts_within_build_zone = True
                val_cost = (
                    data.get("price", 0.0)
                    if isinstance(data, dict)
                    else getattr(data, "price", 0.0)
                )
                val_weight = (
                    data.get("weight_g", 0.0)
                    if isinstance(data, dict)
                    else getattr(data, "weight_g", 0.0)
                )
                metrics.actual_cost = max(metrics.actual_cost, val_cost)
                metrics.actual_weight = max(metrics.actual_weight, val_weight)
                metrics.estimated_cost = max(metrics.estimated_cost, val_cost)
                metrics.estimated_weight = max(metrics.estimated_weight, val_weight)

        # 4. Simulation Result
        if (
            etype == ObservabilityEventType.SIMULATION_REQUEST
            or str(etype) == "simulation_start"
        ):
            metrics.simulation_ran = True
        elif etype == ObservabilityEventType.SIMULATION_RESULT:
            metrics.simulation_ran = True
            success = (
                data.get("success")
                if isinstance(data, dict)
                else getattr(data, "success", False)
            )
            if success:
                metrics.simulation_success = True
                metrics.engineer_implemented_successfully = True
            else:
                metrics.error = str(
                    data.get("failure_reason")
                    if isinstance(data, dict)
                    else getattr(data, "failure_reason", "unknown")
                )

        # 5. Review Decision
        if etype == ObservabilityEventType.REVIEW_DECISION:
            metrics.review_artifacts_complete = True
            decision = (
                data.get("decision")
                if isinstance(data, dict)
                else getattr(data, "decision", None)
            )
            reason = (
                data.get("reason")
                if isinstance(data, dict)
                else getattr(data, "reason", "")
            )
            metrics.reviewer_decision = decision
            metrics.reviewer_feedback = reason
            checklist = (
                data.get("checklist")
                if isinstance(data, dict)
                else getattr(data, "checklist", None)
            )
            if isinstance(checklist, dict):
                metrics.checklist.update(checklist)
            decision_value = str(getattr(decision, "value", decision)).strip().lower()
            if decision_value == ReviewDecision.APPROVED.value.lower():
                metrics.reviewer_accepted = True
            elif decision_value in {
                ReviewDecision.REJECTED.value.lower(),
                ReviewDecision.REJECT_PLAN.value.lower(),
                ReviewDecision.REJECT_CODE.value.lower(),
            }:
                metrics.review_actionable = len(reason) > 20

        # 6. COTS Search
        if etype == ObservabilityEventType.COTS_SEARCH:
            metrics.n_queries += 1
            count = (
                data.get("results_count", 0)
                if isinstance(data, dict)
                else getattr(data, "results_count", 0)
            )
            metrics.n_returned_candidates += count
            if count > 0:
                metrics.n_valid_candidates += count

        # 8. Benchmark specific
        if etype == ObservabilityEventType.SCENE_VALIDATION:
            result = (
                data.get("result")
                if isinstance(data, dict)
                else getattr(data, "result", False)
            )
            if not result:
                metrics.benchmark_constraints_satisfied = False
                errors = (
                    data.get("errors", [])
                    if isinstance(data, dict)
                    else getattr(data, "errors", [])
                )
                metrics.error = ", ".join(errors)

    return metrics
