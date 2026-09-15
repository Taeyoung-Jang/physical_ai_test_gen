# GPT-6 AFS initial implementation

Date: 2026-09-13 UTC.
User request: start introducing GPT-6 into AFS; user will supply API credentials later.
Starting git worktree was clean. This turn implements a bounded initial path without
paid API calls, new GPU rollouts, policy changes or shared-server mutations.

## Delivered scope

New package `scene2test/src/llm_afs`:

- contracts.py: strict proposal schema, domain/path allowlists, finite bounds,
  immutable base revision, exact representative fields, fixed task endpoint validation.
- provider.py: GPT-6 Astra Responses API request using strict JSON schema; fixed official
  endpoint, no redirects/tools/automatic retries; key from OPENAI_API_KEY at call time only.
- workflow.py: labeled demo fixture, representatives + Sobol scene compilation, immutable
  artifacts, duplicates/invalids separated, trusted-local result feedback import.

New CLI: `scene2test/tools/run_llm_afs.py`.
New config: `scene2test/config/llm_afs_terrain.yaml`.
New tests: `test_llm_afs.py`, `test_llm_afs_cli.py`.
Usage and limits: [LLM_AFS_PILOT.md](../scene2test/docs/LLM_AFS_PILOT.md).

Default command prepares context/request only, even with an API key present. --live is
the explicit opt-in to one API attempt. --offline-demo is a deterministic fixture and
is never labeled a model-generated answer. --proposal-file replays saved JSON without
another model call. Every invocation creates a new timestamped runtime directory.

The output is a hypothesized failure-space proposal, not a calibrated surrogate score
or proven failure region. It includes bounded parameter ranges and 1–8 representative
candidates. Up to 32 additional Sobol points can be generated; no silent resampling.

This is a separate **manual-round local pilot**, not an autonomous budgeted experiment
orchestrator or a new general failure_client method. It never auto-launches robot jobs.
The existing isolated terrain runner consumes its suite.json. A later --feedback pair
imports actual results for the next prompt, checking local artifact hashes, scene/revision,
request settings, CUDA provider, and consistent actual code/resource identity.
Mock feedback tests validate this wiring; live adaptive GPT-6 behavior is not measured.

## Input and execution boundaries

Config separates robot, policy, observation and task descriptions. It is extensible in
structure for map-assisted VLM/localization, but v1 only accepts the currently executable
GT map/GT pose + GR00T terrain policy. Unsupported robot VLM/localization flags are
rejected instead of advertising features the runner cannot execute.

Default scene: one ramp with fixed segment layout, scene seed, start/goal and planning
limits. Editable parameters are slope 0–12 degrees, ramp friction 0.15–0.8 and corridor
width 1.4–3.0 m. These are starter domain choices, not certified robot limits. Other
supported continuous recipe attributes can be configured; endpoint-moving changes,
integer topology mutations and arbitrary code/mesh generation are out of scope.

API: gpt-6-astra, reasoning medium, store false, default output cap 4096 tokens,
context cap 250 KB, timeout 120 s, no retry. These are not a dollar-denominated budget.
Incomplete/refused/malformed outputs cannot create scenes. Credentials/headers are
not written to request/protocol files; API error bodies are not logged. Context is
explicitly reviewable before --live. No existing user API key was inspected or used.

Official OpenAI documentation skill was used to check Responses/Structured Outputs:
https://developers.openai.com/api/docs/guides/structured-outputs
https://developers.openai.com/api/docs/models/gpt-6-astra
No live API/schema acceptance or account availability has been verified.

## Verification

Static check:

```bash
.venv/bin/ruff check src/llm_afs tools/run_llm_afs.py tests/test_llm_afs.py tests/test_llm_afs_cli.py
```

Passed. New files were formatted/import-sorted with Ruff.

Full targeted regression from scene2test:

```bash
PYTHONPATH=src .venv/bin/pytest tests/test_llm_afs.py tests/test_llm_afs_cli.py tests/test_terrain_contact_analysis.py tests/test_terrain_courses.py tests/client tests/server tests/test_procedural_world.py tests/test_scene_search.py tests/test_scene_search_runner.py -q
```

**161 passed, 1 existing Starlette/httpx warning, 76.27 seconds.**
This comprises 38 new tests plus 123 prior targeted tests, not every repository phase script.
Provider tests use httpx.MockTransport and placeholder credentials only. Feedback fixtures
are explicitly synthetic; their CUDA labels are test contract data, not GPU evidence.

Checks cover default no-call behavior even with a key present, missing-key refusal,
401/429/500/redirect handling, timeout/no retries, no secret leakage in error strings,
refused/incomplete responses, strict unknown/nonfinite/duplicate/out-of-domain rejection,
actual graph/map/XML exports, deterministic sample revisions, unchanged start/goal,
duplicates, disconnected scenes, feedback artifacts/context/task/fact tampering, and
invalid execution excluded from robot-failure counts. Prior observations change the next
request body; no claim is made that a real LLM has adapted its proposals yet.

## Saved smoke outputs

All under `/workspace/g1_failure/runtime/llm_afs/`:

- `20260913T211706_395269Z`: offline fixture + 2 Sobol points, 3 ready scene bundles.
  Revalidated revisions, checksums and all six artifacts per bundle: SceneSpec,
  SceneGraph, navigation map, XML, preview.png, terrain_map.png. No robot runs/videos.
- `20260913T212018_733945Z`: default request-only mode; no suite/API/GPU call.
- `20260913T212134_837197Z`: saved proposal replay with zero extra samples, 1 ready scene.

Earlier smoke protocol source hashes describe the files at those executions; subsequent
formatting and validation hardening are reflected in current code/tests. These outputs
are preserved and should not be relabeled as GPT-6-generated experimental results.

## Editing limitation

Add File works. Update File still fails at the bwrap helper read stage, including on
new modules. Only files newly authored in this turn were replaced via apply_patch while
developing them; no existing user/source file was overwritten. Shared worker, legacy
AFS, pyproject/uv.lock and server registration remain untouched.

Attempt to add a short architecture update to AGENTS.md failed with the same namespace
error. No replacement was attempted for that existing file. This history and the new
pilot documentation are the current scope update: a GPT-6 API path now exists, but no
live API evidence or autonomous AFS comparison exists yet.

## Next safe steps

User reviews prepared context and supplies OPENAI_API_KEY locally. Explicit --live can
then validate API acceptance. Review the proposal/suite, explicitly run selected scenes
using the existing isolated runner, then import that summary with --feedback for the
next round. No robot VLM or extra manual terrain-performance sweep is required first.
Budgeted autonomous orchestration, complete history selection, broader generators and
fair Random/Sobol/ExtraTrees/LLM comparisons remain later work.

No Git commit/push, services restart, existing evidence deletion or paid API usage occurred.
