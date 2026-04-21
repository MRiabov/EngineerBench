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
