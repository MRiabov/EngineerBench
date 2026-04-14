# Plan Style Traits (Validation Criteria)

This document outlines the stylistic and content traits derived from `desired_architecture.md`. These traits serve as validation criteria for future architectural plans and documentation in this project.

## 1. Unambiguousness

The documentation must be precise and leave little room for interpretation regarding *what* is being built and *what* technologies are used.

- **Specific Technologies**: Explicitly name libraries, frameworks, and tools (e.g., `LangChain`, `build123d`, `Temporal`, `Railway`). Do not say "a workflow engine"; say "Temporal".
- **Concrete Constraints**: Define clear boundaries (e.g., "Execution runs in isolated containers", "Files written directly to worker container").
- **Explicit Rationale**: Provide reasons for key decisions, often citing cost, performance, or simplicity (e.g., "Using `docker-compose` because k8s is too bloated").
- **Defined Success/Failure**: Clearly state what constitutes success or failure (e.g., "Failure is achieved via timeout or out-of-bounds").
- **Versions/Specifics**: Mention specific versions or configurations when relevant (e.g., "DeepSeek 3.2", "Python tools as functions").

## 2. Declarative Language

The documentation should state *what* the system is and *what* it does, rather than *how* to build it step-by-step (imperative).

- **Active Voice**: Use "We use...", "The agent will...", "The system handles...".
- **State-Based**: Describe the desired state of the system (e.g., "The benchmarks are randomized...").
- **Avoid Tutorials**: Do not write "First, install X, then configure Y". Describe the architecture: "The system runs X configured with Y".
- **Rule-Based**: State rules clearly (e.g., "The Agent never 'knows' about distributed workers").

## 3. Minimal Markdown Styling

The documentation should be clean, readable, and devoid of distracting formatting.

- **Standard Headers**: Use standard Markdown headers (`#`, `##`, `###`) for structure.
- **Standard Lists**: Use standard ordered (`1.`) and unordered (`-`) lists.
- **Standard Code Blocks**: Use fenced code blocks (\`\`\`) with language specifiers.
- **No Fancy Components**: Avoid complex HTML, callout blocks (e.g., `> [!NOTE]`), or excessive formatting.
- **Emphasis**: Use bold (`**`) and italics (`*`) sparingly for emphasis only.
- **Simple Tables**: If needed, use simple Markdown tables or YAML blocks for structured data.

## 4. Specific Content Patterns

- **HTML Comments**: Use `<!-- comment -->` for internal notes, questions, future work, or alternative ideas that are not part of the active spec.
- **Problem-Solution-Rationale**: Often structure sections by stating the specific problem or requirement, the chosen solution, and the rationale (e.g., "Latency is acceptable because...").
- **Future-Proofing**: Explicitly mention if a feature is for "Phase 2" or "Future Work", often using comments.
- **Opinionated**: Be clear about *why* a choice was made, even if it's subjective (e.g., "structlog looks nicer").

## 5. Length

- **Longer documents** - 200-500 line documents is minimal. Make longer documents because they are unambiguos <!--this rule is human-written - absolutely ensure it is met -->

## 6. Progressive refinement

- **Progressive refinement** (or a "knowledge fractal") - the documents should be written iteratively, asking "what is underspecified? what are plumbing issues that could arise"? over multiple days. By filling and making opinionated decisions on gaps, good plans arise. <!--this rule is human-written - absolutely ensure it is met -->
- **Focus on plumbing** - a big issue in such plans is lack of good "code plumbing" defintion. This allows very significant leeway in interpretation and the implementation, which, later progresses into ununderstandable code and then refactors, and then an architecture which nobody - not humans not LLMs - understand.

By predefining plumbing, we avoid this issue and later on have a reference point.
