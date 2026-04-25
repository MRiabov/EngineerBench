# EngineerBench: A Unified Framework for Autonomous Benchmark Generation and Physical Problem Solving in Mechanical Engineering

## Abstract

Current Large Language Models (LLMs) excel at symbolic reasoning and software engineering but frequently fail when tasked with complex, physically-grounded mechanical engineering problems. We present **EngineerBench**, an end-to-end agentic framework designed to bridge this gap. The system employs a dual-graph architecture: a **Benchmark Generator** that autonomously synthesizes physics-based puzzles with randomized initial conditions, and an **Engineer Agent** that discovers manufacturable, cost-constrained solutions through iterative CAD drafting, simulation, and Design-for-Manufacturability (DFM) verification. By integrating a high-fidelity simulation engine (Genesis/MuJoCo) with a "workbench" of real-world manufacturing constraints (CNC, Injection Molding, 3D Printing), EngineerBench provides a rigorous platform for evaluating and training the next generation of visual-language models in mechanical design.

## 1. Introduction

The transition from "AI for Code" to "AI for Engineering" requires moving beyond syntax to physical world-models. Engineering involves navigating a high-dimensional space of geometry, materials, costs, and dynamics. EngineerBench formalizes this process by treating engineering as an optimization problem constrained by physics and economic feasibility.

### Key Contributions

- **Dual-Graph Agentic Workflow:** Separates the generation of challenges (Benchmark Generator) from the discovery of solutions (Engineer Agent).
- **Physical Grounding:** Direct integration with the Genesis/MuJoCo simulation environments for empirical verification.
- **Manufacturability Workbenches:** Real-time feedback loops for cost estimation and fabrication feasibility (CNC, IM, 3DP).
- **Episodic Memory & Skill Acquisition:** A structured journaling and skill-creation system that allows agents to learn from failure and persist breakthroughs to a versioned repository.

## 2. System Architecture

EngineerBench is built on a distributed, microservices-oriented architecture designed for durable execution and high-performance physics workloads. The publication bundle is a narrower subset of this development tree, so this README describes the broader repository and not every surface that ships in the bundle.

### 2.1 Dual-Agent Framework

The system utilizes **LangGraph** for orchestration and DSPy-based agent reasoning.

1. **Benchmark Generator Graph:**
   - **Planner:** Designs learning objectives (e.g., gravity, friction, motor dynamics).
   - **CAD Implementer:** Synthesizes the environment using `build123d`.
   - **Reviewer:** Validates the environment for geometry intersections and feasibility.
2. **Engineer Agent Graph:**
   - **Planner (Lead Engineer):** Architecting solutions under strict cost/weight budgets.
   - **Implementer (CAD Coder):** Generates `build123d` code to solve the objective.
   - **Reviewer (Critic):** Scrutinizes stability, efficiency, and reliability of the proposed design.

### 2.2 Distributed Execution Plane

- **Controller (FastAPI):** Orchestrates agent logic and tool calls.
- **Worker-Light:** Handles lightweight filesystem operations, git sync, and linting.
- **Worker-Heavy:** Dedicated compute for Genesis physics simulation, V-HACD convex decomposition, and high-quality rendering.
- **Durable Execution (Temporal):** Development-tree orchestration support for long-running engineering tasks (up to 30+ minutes).

## 3. Methodology

### 3.1 Constraint-Aware CAD (build123d)

Agents interact with a specialized `build123d` environment. Unlike standard CAD, the framework enforces:

- **Rigid Joint Constraints:** Forcing the use of fasteners (`bd-warehouse`) for assembly.
- **Geometric Invariants:** Validating that engineer designs do not violate environment boundaries or "forbid zones."

### 3.2 Design for Manufacturability (DFM)

Every proposed solution is passed through a "Workbench" validator that computes:

- **Cost Models:** CNC setup/machining time, injection molding tool amortization, and material volume costs.
- **Physical Properties:** Precise mass, center of gravity, and moment of inertia calculations.
- **Assembly Validation:** Detection of part interference and under-constrained degrees of freedom (DOFs).

### 3.3 Simulation & Verification

Solutions are converted from CAD to mesh and simulated in **MuJoCo** or **Genesis**.

- **Dynamic Objectives:** Success is defined by the reliable delivery of a `moved_object` to a `goal_zone`.
- **Robustness Testing:** Solutions are evaluated against "runtime jitter" (randomized initial conditions) to ensure mechanical stability.

## 4. Evaluation and Dataset Generation

EngineerBench generates a rich dataset of engineering reasoning:

1. **Reasoning Traces:** Full CoT (Chain-of-Thought) logs of agents designing and failing.
2. **Journals:** Summarized episodic memory of breakthroughs and architectural pivots.
3. **Skills (SKILL.md):** Persisted documentation of learned syntax and engineering patterns.
4. **CAD Library:** A vast, machine-generated library of `build123d` solutions and benchmarks.

## 5. Getting Started

### Prerequisites

- Docker and `docker compose` installed
- Python 3.12+ (uv recommended)

### Installation

```bash
git clone https://github.com/organization/EngineerBench
cd EngineerBench

# install the dependencies for rendering and physical simulation
sudo apt-get update && sudo apt-get install -y --no-install-recommends libgl1 libglu1-mesa libxrender1 libxext6 libfontconfig1 libx11-6 libegl1 libosmesa6 libglib2.0-0 libsm6 libvulkan1 libxcursor1 libxinerama1 libxft2 libxrandr2 libxi6

uv sync # install uv if you haven't: `curl -LsSf https://astral.sh/uv/install.sh | sh`
```

### Running instuction

For a visual demo of a engineer-planner agent (this agent currently does the most complex operations):

#### Step 1: Start the environment:

```sh
./scripts/env_up.sh --profile eval # note: two profiles are available: `interation` (test) and `eval`. `eval` is used for running the actual evaluations
```

#### Step 2: Ensure that the eval seed is good

This is a check that the evaluation row (the geometry and constraints to be evaluated on) are in fact valid. (the row controller by `--task-id`).

```sh
# The agent you are evaluating.
uv run scripts/validate_eval_seed \
    --agent engineer_planner \
    --task-id ep-clearance-gate-06
```

#### Step 3: Run the row (and observe the agents' reasoning):

This will launch the agent's execution.

```sh
# Run the engineer_planner workspace with the visual CLI open.
uv run dataset/evals/materialize_seed_workspace.py \
    --agent engineer_planner \
    --task-id ep-clearance-gate-06 \
    --open-cli-ui \
    --yolo \
    --skip-env-up \
    --provider codex
```

#### Step 4 (optional) Run evaluations batch for a specific agent or run system inference for all (benchmark) agents

Use `dataset/evals/run_evals.py` for the eval runner and
`dataset/evals/eval_inference_pipeline.py` for the application inference pipeline.

Run a specific agent or task with the eval runner:

```sh
uv run dataset/evals/run_evals.py \
    --agent benchmark_planner \
    --task-id ep-clearance-gate-06 \
    --provider qwen \
    --skip-env-up
```

Common eval-runner flags:

- `--agent`: choose the agent to evaluate, or use `all`
- `--task-id`: limit the run to one or more task IDs
- `--level`: limit the run to one or more complexity levels
- `--limit`: cap the number of selected eval items
- `--provider`: choose the local CLI provider
- `--skip-env-up`: reuse an already running stack
- `--queue`: wait for the shared eval lock instead of failing fast (necessary if you've ran evals before)
- `--open-cli-ui`: open local CLI runs in an interactive terminal UI

Run the application inference pipeline directly:

```sh
uv run dataset/evals/eval_inference_pipeline.py \
    --config inference_config.yaml \
    --stage benchmark_planner \
    --author \
    --run-until-stage benchmark_reviewer \
    --skip-env-up
```

*Note*: Due to LLM constraints of engineer_coder and engineer_execution_reviewer not working at the moment, we didn't add functionality to run inference pipeline over them. This is readily extendable, however.

Common inference pipeline flags:

- `--config`: path to `inference_config.yaml`
- `--stage`: choose the starting pipeline stage
- `--run-until-stage`: stop after a downstream stage is reached
- `--author`: run the author/validate/review loop
- `--family`: restrict the run to one or more engineer-planner families
- `--task-id`: limit the run to one or more canonical task IDs
- `--level`: limit the run to one or more complexity levels
- `--limit`: cap the number of selected jobs
- `--provider`: choose `codex` or `qwen`
- `--skip-env-up`: reuse an already running stack
- `--queue`: wait for the shared eval lock instead of failing fast
- `--validate-only`: stop after deterministic validation
- `--persist-results` / `--no-persist-results`: control copy-back into seed storage

### Documentation and specifications

The primary specifications live in `specs/architecture/` files. everything about the system and agents lives there.
See `specs/architecture/desired_architecture.md` for the index.

## 6. Citation

If you use this framework or the generated datasets in your research, please cite:

```bibtex
@article{engineer-bench2026,
  title={EngineerBench: A Unified Framework for Autonomous Benchmark Generation and Physical Problem Solving in Mechanical Engineering},
  author={...},
  journal={arXiv preprint},
  year={2026}
}
```
