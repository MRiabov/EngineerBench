# Problemologist-AI: A Unified Framework for Autonomous Benchmark Generation and Physical Problem Solving in Mechanical Engineering

## Abstract

Current Large Language Models (LLMs) excel at symbolic reasoning and software engineering but frequently fail when tasked with complex, physically-grounded mechanical engineering problems. We present **Problemologist-AI**, an end-to-end agentic framework designed to bridge this gap. The system employs a dual-graph architecture: a **Benchmark Generator** that autonomously synthesizes physics-based puzzles with randomized initial conditions, and an **Engineer Agent** that discovers manufacturable, cost-constrained solutions through iterative CAD drafting, simulation, and Design-for-Manufacturability (DFM) verification. By integrating a high-fidelity simulation engine (Genesis/MuJoCo) with a "workbench" of real-world manufacturing constraints (CNC, Injection Molding, 3D Printing), Problemologist-AI provides a rigorous platform for evaluating and training the next generation of visual-language models in mechanical design.

## 1. Introduction

The transition from "AI for Code" to "AI for Engineering" requires moving beyond syntax to physical world-models. Engineering involves navigating a high-dimensional space of geometry, materials, costs, and dynamics. Problemologist-AI formalizes this process by treating engineering as an optimization problem constrained by physics and economic feasibility.

### Key Contributions

- **Dual-Graph Agentic Workflow:** Separates the generation of challenges (Benchmark Generator) from the discovery of solutions (Engineer Agent).
- **Physical Grounding:** Direct integration with the Genesis/MuJoCo simulation environments for empirical verification.
- **Manufacturability Workbenches:** Real-time feedback loops for cost estimation and fabrication feasibility (CNC, IM, 3DP).
- **Episodic Memory & Skill Acquisition:** A structured journaling and skill-creation system that allows agents to learn from failure and persist breakthroughs to a versioned repository.

## 2. System Architecture

Problemologist-AI is built on a distributed, microservices-oriented architecture designed for durable execution and high-performance physics workloads. The publication bundle is a narrower subset of this development tree, so this README describes the broader repository and not every surface that ships in the bundle.

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

Solutions are converted from CAD to mesh and simulated in **Genesis**.

- **Dynamic Objectives:** Success is defined by the reliable delivery of a `moved_object` to a `goal_zone`.
- **Robustness Testing:** Solutions are evaluated against "runtime jitter" (randomized initial conditions) to ensure mechanical stability.
- **Actuator Limits:** Motors are constrained by real-world torque/power curves, failing if overloaded.

## 4. Evaluation and Dataset Generation

Problemologist-AI generates a rich dataset of engineering reasoning:

1. **Reasoning Traces:** Full CoT (Chain-of-Thought) logs of agents designing and failing.
2. **Journals:** Summarized episodic memory of breakthroughs and architectural pivots.
3. **Skills (SKILL.md):** Persisted documentation of learned syntax and engineering patterns.
4. **CAD Library:** A vast, machine-generated library of `build123d` solutions and benchmarks.

## 5. Getting Started

### Prerequisites

- Docker / Podman
- Python 3.12+ (uv recommended)
- Temporal Server

### Installation

```bash
git clone https://github.com/organization/problemologist-ai
cd problemologist-ai
./scripts/env_up.sh
```

## 6. Citation

If you use this framework or the generated datasets in your research, please cite:

```bibtex
@article{problemologist2026,
  title={Problemologist-AI: Autonomous Mechatronic Design and Benchmarking},
  author={...},
  journal={arXiv preprint},
  year={2026}
}
```
