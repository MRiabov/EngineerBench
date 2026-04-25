| **Project name** | Problemologist-AI: Scalable Synthetic Engineering Benchmark Generation and Simulation for Physical AI |
|---|---|
| Research field | Artificial intelligence, computational mechanics, CAD automation, physics simulation, mechanical engineering design |

**Principal Investigator (PI)**

| Title (Dr., Prof., etc.) |  |
|---|---|
| First (given) name | Maksym |
| Last (family) name | Riabov |
| Organisation name | National College of Ireland |
| Department |  |
| Group |  |
| Country |  |

**Co-PIs/Team members (same information)**



**Co-Principal Investigator (Co-PI)/Team member**

| Title (Dr., Prof., etc.) |  |
|---|---|
| First (given) name |  |
| Last (family) name |  |
| Organisation name |  |
| Department |  |
| Group |  |
| Country |  |

# Key scientific/societal/technological contribution of the proposal (200 words max.)

Problemologist-AI is an open-source framework for generating and solving mechanical engineering benchmark tasks with large vision-language models. Current AI systems are strong at text, software, and image reasoning, but they lack public, high-signal environments for learning manufacturable mechanical design under physical constraints. The project combines agentic benchmark generation, parametric CAD in CadQuery, manufacturability and cost checks, and physics simulation in MuJoCo and Genesis. EuroHPC resources are requested primarily to post-train models that can solve this environment, using supervised fine-tuning and GRPO-style reinforcement learning on generated traces and validated outcomes. The environment itself is lightweight relative to model training, but validating its usefulness requires producing a capable solver model. The expected outcome is both a reusable benchmark/data platform and post-trained open-weight model artifacts for physical design tasks such as moving payloads through constrained environments while respecting cost, mass, geometry, and manufacturing constraints.

# Detailed proposal information (Maximum 8 pages, graphs and tables included)

## Justification for the importance of the scientific problem and the requested resources (1 page)

Mechanical engineering design remains poorly served by current open AI benchmarks. Public datasets exist for code generation, visual question answering, materials property prediction, robotics control, and static CAD reconstruction, but there is no widely usable open benchmark that requires an AI system to design a manufacturable mechanism and then demonstrate, in simulation, that the mechanism performs a physical task. Industrial design data are usually proprietary, and real laboratory validation is too slow and expensive to support the iteration rates needed for model training.

Problemologist-AI targets this gap. The system creates randomized engineering problems, plans and implements candidate solutions, validates CAD correctness, estimates manufacturing cost and weight, and simulates the design to test whether it satisfies objective regions and avoids forbidden regions. The output is not only a pass/fail score. Each run produces structured plans, code-CAD scripts, simulation artifacts, renders, LLM-as-a-Judge review decisions, and compressed reasoning traces. This provides the kind of dense, inspectable training signal that has made software engineering benchmarks valuable for AI research, but for physical design.

The requested EuroHPC allocation is needed primarily for model training on solving the environment, not for the environment runtime itself. For example, fine-tuning Qwen3.5‑35B‑A3B in bf16 LoRA works on 74GB VRAM when training on SFT prediciton; substantially more if the model is trained using Reinforcement Learning. Scaling compute is what will prove the model to be useful for industrial settings.

The target training path is SFT followed by GRPO or closely related online reinforcement learning. Initial experiments have used 9B models, but the main target is a substantially larger model, including a 30B-parameter dense or mixture-of-experts model if the allocation permits. Based on comparable CAD post-training work, for example CADEvolve and CAD modelling research, using SFT plus online RL/GRPO, the expected lower-bound training requirement is approximately 1,500-5,000 H100-hours. 

Notably, the figures above are probably significantly higher, as experimentally, we have proven that models as GPT-5.4 require starting from 100k output token length to solve even basic problems due to numerous trial-and-error (however, solving them in the end). Also notably, one task of this research is to reduce the error rates of the models.

## Overview of the project (2 pages)

The project motivation is that frontier AI models can generate plausible mechanical plans and CAD-like code, but there is still no trustworthy open environment that can train and evaluate them on dynamic, manufacturable engineering tasks. Static CAD reconstruction evaluates geometry syntax or similarity; finite-element-only workflows test isolated structural properties; robotics environments usually assume the robot already exists. Problemologist-AI instead asks the model to create or solve a complete engineering task: for example, move an object (payload) from a start region into a target position while adhering to constraints such as avoiding forbidden regions and cost, weight, material, and manufacturing constraints.

The system has two main agent graphs.

1. The Benchmark Generator graph creates new problems. It plans objective geometry, randomization, allowed build zones, static obstacles, benchmark-owned fixtures, and cost/weight envelopes; a reviewer checks the plan; a coder implements the benchmark; and an execution reviewer accepts only validated benchmark tasks.
2. The Engineer graph solves accepted benchmarks. It plans a mechanism, reviews the plan, generates CadQuery CAD code and simulation artifacts, validates manufacturability and pricing, simulates the candidate, and subjects the final solution to execution review.

The project uses structured handoff artifacts rather than informal chat. Plans, assembly definitions, objective zones, payload trajectories, reviewer decisions, simulation outputs, and render manifests are represented as Markdown, YAML, JSON, or Pydantic-backed schemas. This makes failures reviewable and makes the resulting traces suitable for later model training.

The main computational methods are:

- Parametric code-CAD using CadQuery, selected because it produces editable, reproducible engineering geometry, can export real CAD artifacts, and aligns with more readily available public CAD-code datasets for model training.
- Rigid-body simulation using MuJoCo for fast dynamic validation and Genesis for broader multiphysics extensibility, including future deformables, fluids, and stress-related tasks.
- Manufacturing and economic screening, including cost, weight, material, and process constraints for manufacturing methods such as CNC machining, injection molding, and additive manufacturing.
- Agentic search with planner, coder, reviewer, and skill-improvement roles, using strict validation and fail-closed handoff gates.
- Large-scale ensemble execution, where many independent benchmark/solution episodes run in parallel and each episode emits persistent data for training and evaluation.

The scientific challenges are both computational and methodological. Computationally, the system needs to generate validated traces and then post-train models at a scale large enough to measure real solver improvement. Methodologically, the challenge is to convert loosely stated physical design problems into validated machine-checkable contracts without collapsing to trivial geometry or overfitting to one simulator. Problemologist-AI addresses this by separating static validation, manufacturability checks, dynamic simulation, visual evidence, and reviewer acceptance into distinct gates.

The EuroHPC award will enable the following advances:

- Scale the benchmark corpus from prototype examples to a reusable open dataset of dynamic mechanical design tasks.
- Generate validated solution trajectories, including failed and corrected attempts, that are valuable for post-training and prompt/skill optimization.
- Post-train a solver model using SFT and GRPO-style reinforcement learning to demonstrate that the environment provides a usable training signal.
- Measure model capability across task complexity levels, from simple rigid-body mechanisms to larger multi-part assemblies.
- Evaluate robustness under randomized starts, geometric tolerances, and payload trajectories rather than single deterministic runs.
- Prepare the architecture for multiphysics extensions, including fluids, deformables, and electromechanical tasks.

Expected outcomes are:

- An open-source benchmark-generation and engineering-evaluation framework.
- A dataset of generated benchmark problems with objective definitions, fixtures, renders, and validation metadata.
- A dataset of solution attempts with CAD code, manufacturability checks, cost/weight estimates, simulation results, and reviewer decisions.
- A dataset of reasoning traces and compressed journals for model training and diagnostic analysis.
- Post-trained model checkpoints or adapters, subject to licensing constraints of the selected base model.
- Performance measurements and best practices for running CAD/engineering post-training workloads on HPC systems.

The interdisciplinary value is that the project links machine learning, computational mechanics, CAD, manufacturing, robotics simulation, and software systems. The resulting environment can be used by AI researchers, mechanical engineers, and computational design researchers who need repeatable physical-design tasks rather than only natural-language examples.

## Validation, verification, state of the art (1 page)

### Validation & Verification

The validation strategy is layered. First, every handoff file is checked for structural validity: required Markdown sections, valid YAML/JSON, known schema fields, object labels, units, objective zones, and role-specific file ownership. This prevents downstream stages from silently accepting ambiguous plans.

Second, generated CAD is validated geometrically. The system checks that parts export to valid meshes, that custom-built parts remain inside the build zone, that benchmark-owned fixtures are not modified by the engineer graph, and that static objects and objective zones do not violate declared constraints. Manufacturability checks then test process-relevant constraints such as wall thickness, undercuts, cost estimates, and material assumptions.

Third, dynamic behavior is validated by simulation. The target object must enter the goal region, avoid forbidden zones, and satisfy timing, contact, and payload-trajectory expectations. For robustness, successful solutions are rerun under randomized runtime jitter, start-state variation, and motion envelopes. Simulation evidence includes structured results and visual artifacts so reviewers can inspect both numeric and visual behavior.

Fourth, reviewer agents provide an adversarial validation layer. Plan reviewers reject infeasible, ambiguous, unsupported, or inconsistent handoffs. Execution reviewers inspect static and dynamic evidence and reject non-robust or non-manufacturable solutions. Reviewer behavior is itself evaluated with seeded cases so that approval is not merely a textual formality.

Reproducibility is supported by deterministic session workspaces, strict schemas, persistent render bundles, stored simulation outputs, event logs, and journal summaries. Each accepted artifact can be traced back to the input benchmark, agent role, revision, validation result, and review decision. Local integration tests are used as the primary verification route for service boundaries.

### Comparison with state of the art

Existing CAD-generation benchmarks and tools typically focus on generating code or reconstructing geometry, not on whether a generated mechanism is manufacturable, cost-constrained, and dynamically successful. CAD-GPT, CAD-Llama, STEP-LLM, CADEvolve, CAD-Recode, and related systems are important for text-to-CAD, image-to-CAD, and CAD-sequence generation, but their evaluation is usually static or reconstruction-focused. CADEvolve is especially relevant because it is CadQuery-based and demonstrates the value of large synthetic executable CAD corpora for fine-tuning. Related CAD reconstruction work also shows that SFT followed by online RL methods such as GRPO can improve CAD generation. Problemologist-AI extends this direction from static/reconstruction CAD to dynamic, manufacturable engineering tasks with simulation-backed acceptance.

Robotics and embodied-agent environments evaluate control policies in simulated worlds, but they usually assume the robot or mechanism is already defined. Automated environment-generation systems can synthesize software or embodied tasks, but they do not normally require the model to produce a manufacturable mechanism that satisfies cost and weight constraints.

Problemologist-AI's advantage is the combination of adversarial benchmark generation, code-CAD, manufacturability screening, simulation-backed dynamic objectives, reviewer gates, retained reasoning traces, and a training loop intended to produce a solver model. Its drawback is that model post-training is computationally expensive, especially beyond small models. Environment execution is comparatively lightweight, and simulation validity remains bounded by the chosen physics backends. For this reason the project treats MuJoCo and Genesis as complementary: MuJoCo provides fast rigid-body validation, while Genesis provides a route toward richer multiphysics tasks.

## Software and Attributes (1 page)

### Software

The main codebase is Problemologist-AI, an open-source Python-first platform using FastAPI services, LangGraph/DSPy agent orchestration, strict Pydantic schemas, PostgreSQL, MinIO-compatible object storage, Temporal workflows, and a secondary React/TypeScript dashboard. The scientific workflow uses CadQuery for parametric CAD, MuJoCo for fast rigid-body simulation, Genesis for broader physics simulation, and VTK/OSMesa/EGL-backed rendering for visual evidence. The training workflow will use the generated traces and rewards for SFT and GRPO-style post-training of open-weight models.

The alternatives considered include pure mesh generation, static CAD reconstruction, finite-element-only workflows, and direct reinforcement-learning control environments. These alternatives are not sufficient alone because the project needs editable CAD, manufacturability metadata, cost/weight screening, and dynamic task validation in one loop. CadQuery is the intended CAD basis because it keeps the design editable and closer to manufacturing workflows while also aligning better with the availability of existing public CAD-code datasets.

### Particular libraries

The project uses Python 3.12, CadQuery/OpenCascade-style CAD geometry, MuJoCo, Genesis, FastAPI, Pydantic, SQLAlchemy/Alembic, PostgreSQL, MinIO/S3-compatible storage, Temporal, LangGraph, DSPy, VTK, and supporting scientific Python libraries. Model training will use the selected open-weight model stack for SFT and GRPO-style RL; exact packages and distributed-training configuration should be filled in after the base model and target EuroHPC machine are selected. The frontend uses React, TypeScript, Vite, and Tailwind CSS for inspection only; it is not required for batch production.

The repository is managed with git. Local development and integration execution use the existing project scripts and Python virtual environment. Production HPC execution is expected to use containers or environment modules that provide Python 3.12, compiler/runtime support for CAD and simulation libraries, OpenGL/EGL or OSMesa rendering support, and access to a shared filesystem or object store for artifacts.

### Parallel programming

The environment workload is primarily task-parallel across independent benchmark and solution episodes. Each episode runs controller-side orchestration, worker-light validation, worker-heavy simulation, and worker-renderer preview generation. This environment cost is expected to be small relative to model post-training. The dominant parallel workload is distributed GPU training for SFT and GRPO-style RL, where the model size, sequence length, batch size, rollout strategy, and target machine determine the final data/model parallelism configuration.

### I/O requirements

Each episode writes small structured text files and medium-size binary artifacts. Typical per-episode outputs include Markdown/YAML/JSON handoffs, CAD exports, MJCF or backend simulation files, 24-view RGB/depth/segmentation render bundles, simulation videos, frame metadata, object pose tables, logs, and review records. For planning purposes, a simple rigid-body episode is expected to produce about 50-250 MB, while richer multiphysics or video-heavy episodes may produce 0.5-2 GB. Production should batch artifacts by episode and avoid excessive small-file churn by using manifests and object-store-backed bundles where possible.

The largest file counts occur during active episode workspaces and render bundles. A conservative planning estimate is 100-1,000 files per active episode, with production scheduling limiting simultaneous active episodes per worker group to stay within site file-count policies. Restart overhead is moderate: a failed episode can resume from persisted session files and manifests, but some physics backends have nontrivial cold-start and scene-build costs. Local tests show that warm process reuse can substantially reduce repeated simulation overhead.

## Data: Management Plan, Storage, Analysis and Visualization (~1 page)

### Data Management Plan covering

The project will produce benchmark definitions, CAD scripts, validation logs, simulation results, render bundles, videos, review decisions, event logs, reasoning traces, training datasets, and model outputs such as checkpoints or adapters. Completed episode bundles are designed to be compressed or staged into object-store-style archives with manifest metadata.

Publicly releasable code and datasets are intended to be published through the project repository and a suitable research-data archive. EuroHPC support should be acknowledged in publications and in dataset provenance metadata. The scientific workflow does not require personal data; agent traces contain model and tool outputs, not human-subject records. Credentials, API keys, and operational secrets should be excluded from published artifacts.

### Project workflow

The production workflow has five stages. First, benchmark-generation episodes create candidate tasks and validation evidence. Second, accepted benchmarks are solved by the engineering graph, producing CAD, simulation, and review artifacts. Third, robustness and randomization reruns test accepted solutions across perturbations. Fourth, the resulting traces are converted into SFT and RL training data. Fifth, SFT and GRPO-style training runs produce and evaluate solver models against held-out environment tasks.

The main bottleneck for the requested allocation is model post-training throughput. Simulation throughput, rendering throughput, and transfer of video/render bundles remain engineering concerns, but they are not expected to dominate the compute budget. To reduce data bottlenecks, the workflow stores structured summaries and manifest indices next to large binary artifacts, allowing most analysis and training-data filtering to read metadata before opening videos or images.

### Software workflow solution

Run management is automated through the existing controller/worker architecture and scripts. Temporal workflows coordinate long-running tasks, worker services isolate filesystem, execution, rendering, and simulation responsibilities, and integration-test entrypoints verify service boundaries. Each episode has a session ID, artifact manifests, event records, and review outputs. Batch production will use scripts to submit episode groups, monitor completion, retry failed infrastructure tasks, and export compact dataset bundles.

### I/O requirements

Sustained I/O bandwidth is not expected to be exceptional compared with large CFD or climate simulations, but the workflow benefits from good metadata performance and from staging large immutable artifacts as bundles rather than writing many independent tiny files. Training will additionally require storage for tokenized datasets, rollout logs, reward traces, checkpoints, and evaluation outputs. Final storage volume, retention period, checkpoint policy, and transfer target should be supplied after the target allocation size, base model, and selected system are known.

## Performance of Software (Maximum 2 pages)

### Testing of your code on the requested machine

The preparatory environment evidence currently available in the repository was collected on local development hardware using project scripts under `scripts/experiments/performance`. Target-machine measurements should additionally benchmark the selected SFT and GRPO training stack, since model post-training is the dominant compute requirement.

The environment workload is dominated by independent episode-level jobs. The exact time-to-solution will depend on the target system, but the orchestration pattern, file layout, renderer path, and physics backend behavior are the same. The key measured local results are:

| Experiment | Scenario | Result |
|---|---:|---:|
| 24-view MuJoCo prerender | integration-like cases | 5.65-5.83 s per case |
| 24-view Genesis prerender | integration-like cases | 69.65-72.32 s per case |
| MuJoCo speedup over Genesis for prerender path | integration-like cases | 12.1x-12.8x |
| Fresh child simulation pair | two successful bundles | 125.8-127.9 s total |
| Reused child simulation pair | two successful bundles | 80.2-80.9 s total |
| Warm second simulation task | reused child | 2.44-2.50 s |
| Adaptive payload rotation pruning | demo cases | 52x average speedup over naive grid |

These results support two environment choices: use MuJoCo for high-throughput rigid-body validation where appropriate, and reserve Genesis for workloads that require its richer physics features or for targeted validation subsets. They also show that environment execution is not expected to dominate the requested allocation compared with SFT and GRPO training.

### Quantify the HPC performance of your project

The requested HPC workload is model post-training. The environment runs as a data-generation and reward/evaluation service, while the main performance metric is training throughput and final held-out solve rate. Scaling should therefore be measured through tokens per second, rollout samples per second for GRPO, checkpoint time, and validation pass rate on held-out environment tasks.

#### Strong and weak scalability

For a single environment episode, strong scaling beyond one worker slot is generally not relevant because the episode is constrained by sequential agent decisions, CAD generation, validation, rendering, and simulation. For the full project, strong scaling is relevant to distributed SFT and GRPO training, especially for larger 9B-class and approximately 30B MoE target models.

Weak scaling is relevant in two ways: environment episodes can be distributed across worker slots, and GRPO rollouts/evaluation tasks can be distributed across inference workers. Target-machine scaling measurements should be inserted here once the base model, sequence lengths, batch sizes, and GPU topology are selected.

#### Precision reported

Model post-training is expected to use mixed precision appropriate to the selected training stack, such as bf16/fp16 for model weights, activations, and optimizer states where supported. MuJoCo rigid-body simulation uses double-precision or backend-default floating-point arithmetic depending on the installed build. Genesis uses its backend defaults, commonly mixed or single precision for accelerated kernels. CAD geometry and manufacturability checks use double-precision CPU geometry libraries where exposed by the CAD kernel. The proposal does not require bitwise reproducibility across backends; it requires reproducible task definitions, stored seeds, and acceptance criteria.

#### Time-to-solution

For the environment, normalized time-to-solution is reported per completed validation/simulation job and per accepted episode, rather than per finite-volume cell or molecular-dynamics step. Local measured values show:

- MuJoCo 24-view prerender: approximately 5.7 seconds per integration-like case.
- Genesis 24-view prerender: approximately 70-72 seconds per integration-like case.
- Two successful simulation bundles with fresh child processes: approximately 126-128 seconds.
- The same pair with worker reuse: approximately 80-81 seconds.

These measurements show that environment throughput can be scaled through independent worker slots and should not dominate the allocation. The training time-to-solution should be reported separately as H100-hours or equivalent accelerator-hours for SFT and GRPO runs. The current project estimate is at least 1,500-5,000 H100-hours to train and validate a useful solver model, with the lower end appropriate for smaller models and the upper end for larger or MoE targets.

#### System scale

Current environment values are local preparatory measurements. Final training values should be measured on the selected EuroHPC target system or on a machine with comparable GPU architecture, driver stack, interconnect, and container environment.

#### Measurement mechanism

Environment measurements are collected with script-level wall-clock timers around whole application paths: renderer preview generation, validation-equivalent paths, subprocess simulation, and geometry pruning. Training measurements should use the selected training framework's throughput logs and cluster telemetry, including tokens/s, samples/s, GPU utilization, memory usage, checkpoint time, and held-out evaluation pass rate.

#### Memory usage

Per-worker environment memory depends on the physics backend, render modality, scene complexity, and selected machine. Training memory depends primarily on model size, optimizer, sequence length, batch size, activation checkpointing, parameter sharding, and MoE routing configuration. Target-system memory measurements should be inserted here after benchmarking.

#### OPTIONAL: Percentage of available peak performance

For the environment, peak FLOP utilization is not the most informative metric because the workflow is an agentic ensemble with CAD, Python orchestration, rendering, and physics kernels. For model post-training, GPU utilization and training throughput are central metrics. If required by the selected centre, FLOP or accelerator-utilization metrics will be collected during Benchmark Access using the site-recommended profiler.

# Milestones (quarterly basis) (Maximum 1 page)

| **Run Type** | **Code(s)** | **No. of runs** | **No. of nodes** | **No. of steps per run** | **Time per step(s)** | **Total node hours** |
|---|---|---:|---:|---:|---:|---:|
| A (dataset and trace preparation) | Problemologist-AI, CadQuery, MuJoCo/Genesis |  |  |  | Environment cost comparatively lightweight |  |
| B (SFT post-training) | Selected open-weight model training stack |  |  |  | Training throughput to be benchmarked | Part of 1,500-5,000 H100-hours |
| C (GRPO/RL post-training) | Selected GRPO/RL training stack plus Problemologist-AI reward/eval environment |  |  |  | Training and rollout throughput to be benchmarked | Part of 1,500-5,000 H100-hours |
| D (held-out evaluation and robustness reruns) | Problemologist-AI, MuJoCo/Genesis, analysis scripts |  |  |  | Environment cost comparatively lightweight |  |
| E (checkpoint packaging and analysis) | Training stack, Python analysis |  |  |  |  |  |

## Gantt Chart

| Quarter | Main compute activities | Data/analysis activities | Dissemination |
|---|---|---|---|
| Q1 | Port environment and training stack to selected EuroHPC system; benchmark SFT/GRPO throughput; prepare first training dataset | Validate artifact layout, dataset format, and checkpoint policy | Publish technical setup notes |
| Q2 | Run first SFT training runs on smaller models; evaluate against held-out environment tasks | Aggregate pass/fail modes, cost/weight compliance, and reviewer statistics | Draft dataset/model-card schema and release plan |
| Q3 | Run GRPO-style post-training and scale toward larger models where feasible | Package validated benchmark, solution, training, and checkpoint bundles | Prepare paper/update preprint |
| Q4 | Final training/evaluation reruns for weak areas; freeze best checkpoints/adapters | Produce final metrics, transfer archive | Release code/data/model artifacts where licensing permits and final report |

Communication plan and data-transfer schedule should be supplied according to the final team and target-site constraints.

# Personnel and Management Plan (0,5 page)

The available project material lists Maksym Riabov as the author of the academic submission. The named applicant should populate final personnel roles, institutional details, and management responsibilities.

# References (Maximum 30)

1. R. S. Sutton and A. G. Barto, *Reinforcement Learning: An Introduction*, 2nd ed., MIT Press, 2018.
2. E. Todorov, T. Erez, and Y. Tassa, "MuJoCo: A physics engine for model-based control," *IROS*, 2012.
3. Genesis Authors, "Genesis: A Generative and Universal Physics Engine for Robotics and Beyond," GitHub repository, 2024.
4. CadQuery Contributors, "CadQuery: A Python parametric CAD scripting framework based on OCCT," Zenodo.
5. C. E. Jimenez et al., "SWE-bench: Can language models resolve real-world GitHub issues?" arXiv:2310.06770, 2023.
6. D. M. Bear et al., "Physion: Evaluating physical prediction from vision in humans and machines," arXiv:2106.08261, 2021.
7. Y. Jadhav and A. B. Farimani, "Large language model agent as a mechanical designer," arXiv:2404.17525, 2024.
8. X. Wang et al., "Executable code actions elicit better LLM agents," arXiv:2402.01030, 2024.
9. Q. Wu et al., "AutoGen: Enabling next-gen LLM applications via multi-agent conversation," arXiv:2308.08155, 2023.
10. L. A. Agrawal et al., "GEPA: Reflective prompt evolution can outperform reinforcement learning," arXiv:2507.19457, 2025.
11. L. Zhang, B. Le, N. Akhtar, S.-K. Lam, and D. Ngo, "Large language models for computer-aided design: A survey," *ACM Computing Surveys*, 2026.
12. M. Elistratov, M. Barannikov, G. Ivanov, V. Khrulkov, A. Konushin, A. Kuznetsov, and D. Zhemchuzhnikov, "CADEvolve: Creating Realistic CAD via Program Evolution," arXiv:2602.16317, 2026.
13. M. Kolodiazhnyi et al., "cadrille: Multi-modal CAD Reconstruction with Online Reinforcement Learning," arXiv:2505.22914, 2025.

# Confidentiality (0,5 page)

- Is any part of the project covered by confidentiality? **/**

The project material describes an intended open-source framework and open benchmark/data outputs. Operational credentials, private API keys, and infrastructure configuration secrets should not be included in released artifacts.

- Does your project involve handling of personal data? **/**

The scientific workflow described in the repository does not require personal data. It produces synthetic engineering tasks, model/tool traces, CAD files, simulation outputs, and validation metadata.
