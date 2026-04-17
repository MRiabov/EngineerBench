"""Batched runtime-randomization verification.

Implements the architecture contract:
- one admitted heavy-worker job
- one backend scene build/load
- one backend verification run
- `num_scenes` jittered scene instances inside that run
"""

import os
from dataclasses import dataclass
from typing import Any

from worker_heavy.simulation._mujoco_env import ensure_headless_physics

ensure_headless_physics()

import numpy as np
import structlog

from shared.enums import FailureReason, SimulationConfidence
from shared.models.simulation import (
    MultiRunResult,
    SimulationFailure,
    SimulationMetrics,
)
from shared.simulation.backends import SimulationScene
from shared.simulation.schemas import SimulatorBackendType
from worker_heavy.simulation.evaluator import SuccessEvaluator
from worker_heavy.simulation.naming import (
    is_payload_scene_name,
    payload_scene_name,
)

logger = structlog.get_logger(__name__)

DEFAULT_NUM_SCENES = 5


@dataclass
class _SceneOutcome:
    success: bool = False
    failure: SimulationFailure | None = None
    total_time: float = 0.0
    max_velocity: float = 0.0
    done: bool = False


def _identify_target_body_name(
    body_names: list[str], explicit_target_body_name: str | None = None
) -> str | None:
    if explicit_target_body_name and explicit_target_body_name in body_names:
        return explicit_target_body_name

    if explicit_target_body_name:
        namespaced_target = payload_scene_name(explicit_target_body_name)
        if namespaced_target in body_names:
            return namespaced_target

    preferred = ("target_box", "projectile_ball")
    for name in preferred:
        if name in body_names:
            return name

    for name in body_names:
        if is_payload_scene_name(name):
            return name

    for name in body_names:
        lowered = name.lower()
        if "target" in lowered or "projectile" in lowered or "ball" in lowered:
            return name

    return None


def _build_metrics(outcome: _SceneOutcome) -> SimulationMetrics:
    failure = outcome.failure
    return SimulationMetrics(
        total_time=outcome.total_time,
        total_energy=0.0,
        max_velocity=outcome.max_velocity,
        success=outcome.success,
        fail_reason=str(failure) if failure else None,
        fail_mode=failure.reason if failure else None,
        failure=failure,
        confidence=SimulationConfidence.HIGH,
    )


def _finalize_pending_outcomes(
    outcomes: list[_SceneOutcome],
    duration: float,
    goal_sites: list[str],
) -> None:
    for outcome in outcomes:
        if outcome.done:
            continue
        outcome.total_time = duration
        outcome.success = not goal_sites
        outcome.done = True


def _mujoco_apply_control(
    model: Any, data: Any, control_inputs: dict[str, float]
) -> None:
    if not control_inputs:
        return

    import mujoco

    for name, value in control_inputs.items():
        actuator_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_ACTUATOR, name)
        if actuator_id != -1:
            data.ctrl[actuator_id] = value


def _mujoco_build_control_trajectory(
    model: Any,
    control_inputs: dict[str, float],
    batch_size: int,
    steps: int,
) -> np.ndarray | None:
    if not control_inputs:
        return None

    import mujoco

    ncontrol = mujoco.mj_stateSize(model, mujoco.mjtState.mjSTATE_CTRL.value)
    controls = np.zeros((batch_size, steps, ncontrol), dtype=np.float64)
    for name, value in control_inputs.items():
        actuator_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_ACTUATOR, name)
        if actuator_id != -1:
            controls[:, :, actuator_id] = value
    return controls


def _mujoco_set_state_and_forward(model: Any, data: Any, state: np.ndarray) -> None:
    import mujoco

    mujoco.mj_setState(
        model,
        data,
        state,
        mujoco.mjtState.mjSTATE_FULLPHYSICS.value,
    )
    mujoco.mj_forward(model, data)


def _mujoco_body_names(model: Any) -> list[str]:
    import mujoco

    names: list[str] = []
    for i in range(model.nbody):
        name = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_BODY, i)
        if name and name not in {"world", "0"} and not name.startswith("zone_"):
            names.append(name)
    return names


def _mujoco_body_records(model: Any) -> list[tuple[str, int, bool]]:
    import mujoco

    records: list[tuple[str, int, bool]] = []
    for body_id in range(model.nbody):
        name = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_BODY, body_id)
        if name and name not in {"world", "0"} and not name.startswith("zone_"):
            # Bodies with joints can move over time; fixed bodies can be checked
            # once because their world pose does not change during replay.
            records.append((name, body_id, bool(model.body_jntnum[body_id] > 0)))
    return records


def _mujoco_site_names(model: Any, prefix: str) -> list[str]:
    import mujoco

    names: list[str] = []
    for i in range(model.nsite):
        name = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_SITE, i)
        if name and name.startswith(prefix):
            names.append(name)
    return names


def _mujoco_site_ids(model: Any, prefix: str) -> list[int]:
    import mujoco

    ids: list[int] = []
    for site_id in range(model.nsite):
        name = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_SITE, site_id)
        if name and name.startswith(prefix):
            ids.append(site_id)
    return ids


def _mujoco_apply_jitter(
    model: Any, data: Any, body_name: str, jitter: tuple[float, float, float]
) -> None:
    import mujoco

    body_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, body_name)
    if body_id == -1:
        return

    jnt_adr = model.body_jntadr[body_id]
    jnt_num = model.body_jntnum[body_id]
    for i in range(jnt_num):
        joint_id = jnt_adr + i
        if model.jnt_type[joint_id] == mujoco.mjtJoint.mjJNT_FREE:
            q_adr = model.jnt_qposadr[joint_id]
            data.qpos[q_adr : q_adr + 3] += np.array(jitter)
            mujoco.mj_forward(model, data)
            return


def _mujoco_get_state_vector(model: Any, data: Any) -> np.ndarray:
    import mujoco

    nstate = mujoco.mj_stateSize(model, mujoco.mjtState.mjSTATE_FULLPHYSICS.value)
    state = np.empty(nstate, dtype=np.float64)
    mujoco.mj_getState(model, data, state, mujoco.mjtState.mjSTATE_FULLPHYSICS.value)
    return state


def _mujoco_get_body_state_by_id(
    model: Any, data: Any, body_id: int
) -> tuple[np.ndarray, np.ndarray]:
    if body_id == -1:
        return np.zeros(3), np.zeros(3)

    pos = np.array(data.xpos[body_id], copy=True)
    vel = np.array(data.cvel[body_id][3:], copy=True)
    return pos, vel


def _mujoco_get_body_state(
    model: Any, data: Any, body_name: str
) -> tuple[np.ndarray, np.ndarray]:
    import mujoco

    body_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, body_name)
    return _mujoco_get_body_state_by_id(model, data, body_id)


def _mujoco_check_collision_by_id(
    model: Any, data: Any, body_id: int, site_id: int
) -> bool:
    import mujoco

    if body_id == -1 or site_id == -1:
        return False

    geom_start = model.body_geomadr[body_id]
    geom_num = model.body_geomnum[body_id]

    zone_pos = data.site_xpos[site_id]
    zone_size = model.site_size[site_id]
    zone_type = model.site_type[site_id]
    site_mat = data.site_xmat[site_id].reshape(3, 3)

    if geom_num == 0:
        body_pos = data.xpos[body_id]
        diff = body_pos - zone_pos
        v_local = diff @ site_mat
        if zone_type == mujoco.mjtGeom.mjGEOM_BOX:
            return bool(np.all(np.abs(v_local) <= zone_size[:3]))
        if zone_type == mujoco.mjtGeom.mjGEOM_SPHERE:
            return bool(np.linalg.norm(diff) <= zone_size[0])
        return False

    for i in range(geom_num):
        geom_id = geom_start + i
        geom_type = model.geom_type[geom_id]
        geom_pos = data.geom_xpos[geom_id]
        geom_mat = data.geom_xmat[geom_id].reshape(3, 3)

        geom_rbound = model.geom_rbound[geom_id]
        max_site_dist = np.max(zone_size[:3])
        dist = np.linalg.norm(geom_pos - zone_pos)
        if dist > geom_rbound + max_site_dist + 0.01:
            continue

        if geom_type == mujoco.mjtGeom.mjGEOM_MESH:
            mesh_id = model.geom_dataid[geom_id]
            vert_adr = model.mesh_vertadr[mesh_id]
            vert_num = model.mesh_vertnum[mesh_id]
            raw_verts = model.mesh_vert[vert_adr : vert_adr + vert_num]
            vertices = geom_pos + raw_verts @ geom_mat.T
        else:
            vertices = np.array([geom_pos])

        if zone_type == mujoco.mjtGeom.mjGEOM_BOX:
            diff = vertices - zone_pos
            v_local = diff @ site_mat
            if np.any(np.all(np.abs(np.atleast_2d(v_local)) <= zone_size[:3], axis=1)):
                return True
        elif zone_type == mujoco.mjtGeom.mjGEOM_SPHERE:
            diff = vertices - zone_pos
            if np.any(np.linalg.norm(np.atleast_2d(diff), axis=1) < zone_size[0]):
                return True

    return False


def _mujoco_check_collision(
    model: Any, data: Any, body_name: str, site_name: str
) -> bool:
    import mujoco

    body_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, body_name)
    site_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_SITE, site_name)
    return _mujoco_check_collision_by_id(model, data, body_id, site_id)


def _verify_mujoco_batched(
    xml_path: str,
    control_inputs: dict[str, float],
    jitter_range: tuple[float, float, float],
    num_scenes: int,
    duration: float,
    seed: int,
    explicit_target_body_name: str | None = None,
) -> MultiRunResult:
    import mujoco
    from mujoco.rollout import Rollout

    model = mujoco.MjModel.from_xml_path(xml_path)
    body_records = _mujoco_body_records(model)
    body_names = [name for name, _, _ in body_records]
    # The replay loop is hot enough that we keep body/site identities in
    # integer form once the scene is loaded. That lets the threaded rollout feed
    # a lighter serial replay pass without repeated name lookups.
    moving_body_records = [
        (name, body_id) for name, body_id, is_dynamic in body_records if is_dynamic
    ]
    static_body_records = [
        (name, body_id) for name, body_id, is_dynamic in body_records if not is_dynamic
    ]
    goal_sites = _mujoco_site_names(model, "zone_goal")
    goal_site_ids = _mujoco_site_ids(model, "zone_goal")
    forbid_site_ids = _mujoco_site_ids(model, "zone_forbid")
    target_body_name = _identify_target_body_name(
        body_names, explicit_target_body_name=explicit_target_body_name
    )
    target_body_id = -1
    if target_body_name:
        target_body_id = mujoco.mj_name2id(
            model, mujoco.mjtObj.mjOBJ_BODY, target_body_name
        )
    outcomes = [_SceneOutcome() for _ in range(num_scenes)]
    evaluators = [
        SuccessEvaluator(max_simulation_time=duration) for _ in range(num_scenes)
    ]
    rng = np.random.default_rng(seed)
    scene_datas = [mujoco.MjData(model) for _ in range(num_scenes)]

    if target_body_name:
        for data in scene_datas:
            jitter = (
                rng.uniform(-jitter_range[0], jitter_range[0]),
                rng.uniform(-jitter_range[1], jitter_range[1]),
                rng.uniform(-jitter_range[2], jitter_range[2]),
            )
            _mujoco_apply_jitter(model, data, target_body_name, jitter)

    dt = float(model.opt.timestep)
    steps = max(1, int(duration / dt))
    control_trajectory = _mujoco_build_control_trajectory(
        model,
        control_inputs,
        num_scenes,
        steps,
    )
    nthread = max(1, min(num_scenes, os.cpu_count() or num_scenes))
    rollout_datas = [mujoco.MjData(model) for _ in range(nthread)]

    # Static bodies never move, so we can validate their time-invariant failure
    # conditions once up front. That keeps the replay loop focused on the bodies
    # whose pose actually changes with the rollout state.
    if static_body_records:
        baseline_data = scene_datas[0]
        static_failure: SimulationFailure | None = None
        for body_name, body_id in static_body_records:
            pos, vel = _mujoco_get_body_state_by_id(model, baseline_data, body_id)
            fail_reason = evaluators[0].check_failure(0.0, pos, vel)
            if fail_reason:
                static_failure = SimulationFailure(
                    reason=fail_reason,
                    detail=body_name,
                )
                break

            if forbid_site_ids and any(
                _mujoco_check_collision_by_id(model, baseline_data, body_id, site_id)
                for site_id in forbid_site_ids
            ):
                static_failure = SimulationFailure(
                    reason=FailureReason.FORBID_ZONE_HIT,
                    detail=body_name,
                )
                break

        if static_failure is not None:
            for outcome in outcomes:
                outcome.failure = static_failure
                outcome.done = True
            _finalize_pending_outcomes(
                outcomes, duration=duration, goal_sites=goal_sites
            )
            results = [_build_metrics(outcome) for outcome in outcomes]
            success_count = sum(1 for result in results if result.success)
            success_rate = success_count / num_scenes if num_scenes > 0 else 0.0
            fail_reasons = list(
                {
                    result.fail_reason
                    for result in results
                    if result.fail_reason is not None
                }
            )
            return MultiRunResult(
                num_scenes=num_scenes,
                success_count=success_count,
                success_rate=success_rate,
                is_consistent=(len({result.success for result in results}) == 1),
                individual_results=results,
                fail_reasons=fail_reasons,
                scene_build_count=1,
                backend_run_count=1,
                batched_execution=True,
            )

    with Rollout(nthread=nthread) as rollout:
        states, _sensordata = rollout.rollout(
            model,
            rollout_datas,
            np.stack(
                [_mujoco_get_state_vector(model, data) for data in scene_datas],
                axis=0,
            ),
            control=control_trajectory,
            nstep=steps,
        )

    scratch_data = mujoco.MjData(model)
    # Rollout owns the expensive batched stepping; replay returned states through
    # mj_forward so the existing collision, velocity, and timeout checks still
    # run against full derived scene data. This replay remains serial because it
    # needs explicit per-scene early exits and derived MuJoCo state.
    for idx, outcome in enumerate(outcomes):
        if outcome.done:
            continue

        for step_idx in range(steps):
            _mujoco_set_state_and_forward(
                model,
                scratch_data,
                states[idx, step_idx],
            )
            current_time = float(scratch_data.time)
            outcome.total_time = current_time

            for body_name, body_id in moving_body_records:
                pos, vel = _mujoco_get_body_state_by_id(model, scratch_data, body_id)
                outcome.max_velocity = max(
                    outcome.max_velocity, float(np.linalg.norm(vel))
                )
                fail_reason = evaluators[idx].check_failure(current_time, pos, vel)
                if fail_reason:
                    outcome.failure = SimulationFailure(
                        reason=fail_reason,
                        detail=body_name,
                    )
                    outcome.done = True
                    break

            if outcome.done:
                break

            for body_name, body_id in moving_body_records:
                if any(
                    _mujoco_check_collision_by_id(model, scratch_data, body_id, site_id)
                    for site_id in forbid_site_ids
                ):
                    outcome.failure = SimulationFailure(
                        reason=FailureReason.FORBID_ZONE_HIT,
                        detail=body_name,
                    )
                    outcome.done = True
                    break

            if outcome.done:
                break

            if target_body_id != -1 and any(
                _mujoco_check_collision_by_id(
                    model, scratch_data, target_body_id, site_id
                )
                for site_id in goal_site_ids
            ):
                outcome.success = True
                outcome.done = True
                break

    _finalize_pending_outcomes(outcomes, duration=duration, goal_sites=goal_sites)

    results = [_build_metrics(outcome) for outcome in outcomes]
    success_count = sum(1 for result in results if result.success)
    success_rate = success_count / num_scenes if num_scenes > 0 else 0.0
    fail_reasons = list(
        {result.fail_reason for result in results if result.fail_reason is not None}
    )

    return MultiRunResult(
        num_scenes=num_scenes,
        success_count=success_count,
        success_rate=success_rate,
        is_consistent=(len({result.success for result in results}) == 1),
        individual_results=results,
        fail_reasons=fail_reasons,
        scene_build_count=1,
        backend_run_count=1,
        batched_execution=True,
    )


def _verify_genesis_batched(
    xml_path: str,
    control_inputs: dict[str, float],
    jitter_range: tuple[float, float, float],
    num_scenes: int,
    duration: float,
    seed: int,
    smoke_test_mode: bool | None,
    session_id: str | None,
    explicit_target_body_name: str | None = None,
) -> MultiRunResult:
    from worker_heavy.simulation.genesis_backend import GenesisBackend

    backend = GenesisBackend(session_id=session_id, num_envs=num_scenes)
    backend.smoke_test_mode = bool(smoke_test_mode)
    backend.load_scene(SimulationScene(scene_path=xml_path))

    body_names = [
        name
        for name in backend.get_all_body_names()
        if name not in {"mjcf_scene"} and not name.startswith("zone_")
    ]
    goal_sites = [
        name for name in backend.get_all_site_names() if name.startswith("zone_goal")
    ]
    forbid_sites = [
        name for name in backend.get_all_site_names() if name.startswith("zone_forbid")
    ]
    target_body_name = _identify_target_body_name(
        body_names, explicit_target_body_name=explicit_target_body_name
    )
    outcomes = [_SceneOutcome() for _ in range(num_scenes)]
    evaluators = [
        SuccessEvaluator(max_simulation_time=duration, session_id=session_id)
        for _ in range(num_scenes)
    ]
    rng = np.random.default_rng(seed)

    if target_body_name:
        for env_idx in range(num_scenes):
            jitter = (
                rng.uniform(-jitter_range[0], jitter_range[0]),
                rng.uniform(-jitter_range[1], jitter_range[1]),
                rng.uniform(-jitter_range[2], jitter_range[2]),
            )
            backend.apply_jitter(target_body_name, jitter, env_idx=env_idx)

    if control_inputs:
        backend.apply_control(control_inputs)

    dt = getattr(backend, "timestep", 0.002)
    steps = max(1, int(duration / dt))

    for _ in range(steps):
        if all(outcome.done for outcome in outcomes):
            break

        res = backend.step(dt)
        current_time = float(res.time)

        for env_idx, outcome in enumerate(outcomes):
            if outcome.done:
                continue

            outcome.total_time = current_time
            if not res.success:
                if res.failure:
                    outcome.failure = res.failure
                else:
                    outcome.failure = SimulationFailure(
                        reason=FailureReason.PHYSICS_INSTABILITY,
                        detail=str(getattr(res, "failure_reason", "backend failure")),
                    )
                outcome.done = True
                continue

            for body_name in body_names:
                state = backend.get_body_state(body_name, env_idx=env_idx)
                vel_norm = float(np.linalg.norm(state.vel))
                outcome.max_velocity = max(outcome.max_velocity, vel_norm)
                fail_reason = evaluators[env_idx].check_failure(
                    current_time,
                    np.array(state.pos),
                    np.array(state.vel),
                )
                if fail_reason:
                    outcome.failure = SimulationFailure(
                        reason=fail_reason,
                        detail=body_name,
                    )
                    outcome.done = True
                    break

            if outcome.done:
                continue

            for body_name in body_names:
                if any(
                    backend.check_collision(body_name, site_name, env_idx=env_idx)
                    for site_name in forbid_sites
                ):
                    outcome.failure = SimulationFailure(
                        reason=FailureReason.FORBID_ZONE_HIT,
                        detail=body_name,
                    )
                    outcome.done = True
                    break

            if outcome.done:
                continue

            if target_body_name and any(
                backend.check_collision(target_body_name, site_name, env_idx=env_idx)
                for site_name in goal_sites
            ):
                outcome.success = True
                outcome.done = True

    _finalize_pending_outcomes(outcomes, duration=duration, goal_sites=goal_sites)

    results = [_build_metrics(outcome) for outcome in outcomes]
    success_count = sum(1 for result in results if result.success)
    success_rate = success_count / num_scenes if num_scenes > 0 else 0.0
    fail_reasons = list(
        {result.fail_reason for result in results if result.fail_reason is not None}
    )

    return MultiRunResult(
        num_scenes=num_scenes,
        success_count=success_count,
        success_rate=success_rate,
        is_consistent=(len({result.success for result in results}) == 1),
        individual_results=results,
        fail_reasons=fail_reasons,
        scene_build_count=1,
        backend_run_count=1,
        batched_execution=True,
    )


def verify_with_jitter(
    xml_path: str,
    control_inputs: dict[str, float],
    jitter_range: tuple[float, float, float] = (0.002, 0.002, 0.001),
    num_scenes: int = DEFAULT_NUM_SCENES,
    duration: float = 10.0,
    seed: int = 42,
    dynamic_controllers: dict[str, Any] | None = None,
    backend_type: SimulatorBackendType = SimulatorBackendType.MUJOCO,
    session_id: str | None = None,
    smoke_test_mode: bool | None = None,
    explicit_target_body_name: str | None = None,
) -> MultiRunResult:
    """Run one batched verification over multiple jittered scene instances."""
    if dynamic_controllers:
        raise NotImplementedError(
            "Batched verification does not support dynamic controllers yet."
        )

    if isinstance(backend_type, str):
        backend_type = SimulatorBackendType(backend_type)

    logger.info(
        "verification_batch_start",
        backend=backend_type.value,
        num_scenes=num_scenes,
        duration=duration,
        session_id=session_id,
    )

    if backend_type == SimulatorBackendType.GENESIS:
        return _verify_genesis_batched(
            xml_path=xml_path,
            control_inputs=control_inputs,
            jitter_range=jitter_range,
            num_scenes=num_scenes,
            duration=duration,
            seed=seed,
            smoke_test_mode=smoke_test_mode,
            session_id=session_id,
            explicit_target_body_name=explicit_target_body_name,
        )

    if backend_type == SimulatorBackendType.MUJOCO:
        return _verify_mujoco_batched(
            xml_path=xml_path,
            control_inputs=control_inputs,
            jitter_range=jitter_range,
            num_scenes=num_scenes,
            duration=duration,
            seed=seed,
            explicit_target_body_name=explicit_target_body_name,
        )

    raise ValueError(f"Unsupported backend for verification: {backend_type}")
