# DRAFT: ideas for when we'll need to fine-tune

<!--Note: this is a complete WIP doc. It's not a reference, none of this was implemented yet.
It also is too early to implement too-->

## Environment

- Without a working env it won't work.

## Tools

- Fine-tune using Unsloth models
  - Unsloth has it's long-context-window fine tuning
  - Not confirmed if it has vision capabilties.
    Axolotl also had some ideas
    Nvidia NeMo Gym also did something similar.

## Uncategorized ideas

- Finetuning with 32k max context may work because there is no particular need in stretching context further for solving such simple tasks as we have.

## SFT dataset of reasoning traces

Top works currently utilize large-scale continuous "standard-quality" training and SFT on high quality data for models. We need a dataset of building correct solutions in order for the model to understand semantics and reasoning patterns. To implement we need:

- A dataset of working, physically and code-wise valid and quality solutions
- A dataset of working solutions.

## SFT dataset of build123d data:

We could try to deterministically convert ABC and other CAD datasets to use build123d to teach the model build123d semantics.

## Engineer-planner and engineer-plan-reviewer is a dead weight

Engineer-planner could be a dead weight at the moment. Why bother? we can simply validate that a solution is correct at runtime... And while we have examples of this not working, well...

## Continous pre-training on a CAD image dataset?

Continuous pretraining may be done on a image dataset such as a visual image

## Video-playing models

There was a number of models that are doing pre-training on gameplaying models. I assume they might have suitable embeddings? maybe not.

<!--Note: I may want to apply for an innovation voucher. I also must apply for the computation voucher. That means applying for VAT.-->

## Automatic skill tuning

Projects like SkillClaw handle skill tuning, but it looks very strangely implemented.

## RL interfaces

There is a number of RL interfaces already available. SWE-smith uses them

## Move to cadquery

Models struggle already, and cadquery has a supreme amount of training data on the internet. Fine-tuned models available already. Why bother training a model from scratch if I can train a CQ model?
Also, CQ appears to be quite forgiving too.

## Reuse already trained models

Why bother with fine-tuning an existing model if I can fine-tune already strong for CAD models like InCoder and others? Yes, they are worse, but.

## Boil the environment down?

Planning is useful, but: not necessary
What this entire architecture really needs is:

1. We copy a set of scripts - to validate CAD and to validate agents, which are already mostly there
2. We let it run on a daytona container.

An environment is but a python package.

## Other datasets:

### Do features intersect?

Give a set of build123d or cadquery code. Ask the model if the two intersect

### Estimate the volume of a complex CAD feature

Estimate a volume of a complex CAD feature without access to CAD kernel or internet (math feature, basically)

#### Comparative features

"You are given two CAD features. Which one from them has the lowest/largest volume"
"You are given two CAD features, with different materials. Will it pass?

### Will feature pass through?

"You are given an "environment" renders and build123d CAD code and a "payload" render. You are also given a path of the payload. Based on the geometry and renders, will you pass the environment?
