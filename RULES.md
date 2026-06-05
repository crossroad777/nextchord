# NEXTCHORD (BASELINEDESIGNS) - Repository Rules

## Non-negotiable architecture

- Single Source of Truth: UMR is the only truth.
- Strict separation:
  - ingest/* : I/O boundary + estimators (may use external libs)
  - core/*   : domain & theory (NO external MIR deps)
  - render/* : notation/rendering (NO external MIR deps)
  - pipeline/* : orchestration only
- No hidden magic: no global mutable state, no implicit auto-fix. Everything explicit.

## Dependency policy (keep this)

- librosa: OK (ingest/audio/features only)
- madmom: OK (ingest/audio/features or estimators only)
- essentia: CONDITIONAL
  - MUST NOT be linked/imported in core/*
  - Allowed only as external process wrapper under ingest/audio/extern/*
  - Output must be serialized features (json) with provenance
- deep learning models: pluggable estimators only; trained model usage requires license clarity.

## Coding rules

- Prefer pure functions in core/theory/render.
- All transformations must be named and typed; no ad-hoc dict blobs.
- Return Result/Either for recoverable failures; exceptions only for bugs/IO unexpected.
- Keep provenance & confidence on inferred data.
- No circular imports; split responsibilities instead.
- Tests: start from invariants (UMR consistency).

## MVP backbone goal

Make this pipeline run end-to-end:
midi -> UMR -> validate -> interpret -> render(chords, musicxml, tab stub) -> CLI output
Even if estimators are stubs, the pipeline must execute and tests must pass.

## Regression Prevention & Version Control Policy

- **Commit frequently**: Every fix or feature must be committed to git immediately once verified. Do not let changes sit unstaged or uncommitted.
- **Do not bypass local testing**: Run test scripts (like those in `scratch/`) to verify external APIs (e.g., Groq Whisper) and ensure proper return types before pushing or deploying.
- **Document API integrations**: Always document expected structures and formats of external services (like Groq's verbose_json output) to avoid subtle structural regressions.
- **Deploy only committed code**: When deploying to Hugging Face Spaces (e.g., `hf` or `hf2` remotes), deploy from a clean git branch. Never push raw, uncommitted code manually.

