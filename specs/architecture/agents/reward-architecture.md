# Reward config structure

`config/reward_config.yaml` is split into three metric classes per agent when reward shaping is used:

1. `hard_checks`: deterministic or directly computed checks such as artifact presence, schema validity, geometry validity, pricing caps, manufacturability, and simulation outcomes that do not require an LLM judge.
2. `judge_evaluation`: reviewer-driven or seeded-rubric metrics such as reviewer acceptance, decision correctness, actionability, and feedback-response quality.
3. `judge_evaluation.checklist`: weighted per-checklist-item reward terms that deliberately duplicate the canonical reviewer checklist. Each checklist key is rewarded individually rather than via one aggregate checklist score.
4. `milestones`: remaining non-review objective rewards that are neither pure fail-closed gates nor LLM-as-a-judge outputs. This bucket is allowed for backward compatibility and for downstream objective outcomes such as "planner led to successful implementation".

Rules:

1. Weights across `hard_checks`, `judge_evaluation`, `judge_evaluation.checklist`, and `milestones` sum to `1.0` per agent.
2. Reviewer-heavy agents should score canonical checklist keys individually rather than hiding checklist quality behind one aggregate checklist scalar.
3. Planner and coder agents may intentionally duplicate reviewer checklist keys in reward config when those keys represent the real quality gates for acceptance.
4. Coder agents should carry explicit reward for handling reviewer feedback, including partial credit for fixing valid failed checklist items and resisting incorrect reviewer requests in mixed-quality feedback evals.
