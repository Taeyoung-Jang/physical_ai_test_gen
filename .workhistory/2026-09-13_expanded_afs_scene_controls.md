# Expanded scene controls and mixed AFS exploration

Date: 2026-09-13 UTC. User approved implementing expanded environmental controls and
more active scene-space exploration. Work is scoped to AFS, not improving G1 gait.

## Starting state and decisions

- Initial git status contained only the existing untracked initial-AFS history file.
  Existing v1 code was committed and was preserved; no git commit/push was performed.
- v1 explicitly freezes seed, segment order, topology and endpoints. Silently broadening
  that contract would break its claim boundaries. Added opt-in v2 modules/config/CLI.
- Reused existing terrain generator, SceneGraph/map/XML export and bundle validation.
  No shared generator, navigation server, worker, robot model or controller was modified.
- Structural changes are selected from user-approved recipe templates. LLM cannot emit
  arbitrary executable code/XML or create unrecognized geometry kinds.
- Existing terrain recipe capability is now reachable through typed AFS domains:
  continuous values, integer counts/seeds, categorical patterns, vector size components.
- Endpoint changes are explicit: `generated_course_end` permits different task instances
  while freezing speed/duration and success criteria; `fixed` rejects endpoint changes.
  Course length must be considered when interpreting failure rates.

## Files added

- `scene2test/src/llm_afs/expanded.py`: strict v2 config/proposal models, allowlisted paths,
  bounded subset validation, multi-layout SceneGraph context, deterministic scene
  compiler, verified feedback wrapper and mixed exploration scheduler.
- `scene2test/tools/run_expanded_afs.py`: request-only default, explicit paid live call,
  offline fixture, proposal replay, Random/Sobol baselines, feedback import, provenance.
- `scene2test/config/llm_afs_expanded.yaml`: four multi-factor layouts: ramp→obstacles,
  obstacles→ramp, stairs→bottleneck, rough→friction.
- `scene2test/tests/test_expanded_afs.py` and `test_expanded_afs_feedback.py`.
- `scene2test/docs/EXPANDED_LLM_AFS.md`: controls, contracts, budgets, commands, limitations.

## Exploration semantics

Every four mixed attempts allocate two to full allowed-domain exploration, one to an
LLM-proposed joint space, and one to a verified failure neighborhood. If no actual
failure feedback exists, the last slot also explores the full domain. The initial
offline example therefore has 75% full-space exploration, 25% fixture-proposed space.

Continuous neighborhoods use 15% of original domain width; integer neighborhoods use
at least one step. Bounds are clipped; categorical pattern and scene seed retain full
exploration. Layout coverage cycles independently of proposal/local slots. Several
factors vary together to expose interactions, not to estimate causal contributions.

Feedback inherits v1 config/context/suite/request/resource/code/artifact checks and
requires recorded CUDA provider and consistent execution identity. The wrapper adds
the originating layout. Only EVALUATED `robot_failure: true` observations seed local
search. Synthetic test observations are expressly not evidence of GPU execution.

## Validation performed

- Expanded contracts/real geometry/CLI tests: 18 passed in 41.70 seconds.
- V2 hashed synthetic feedback plus existing v1 AFS tests: 40 passed in 20.12 seconds.
- Terrain, procedural-world, scene-search, contact analysis, terrain guard regression:
  58 passed in 34.74 seconds.
- Combined total across these disjoint test selections: 116 passed.
- Ruff check passed for all four new Python files after formatting.
- Seed-17 offline fixture: 12 attempts, 10 READY bundles, 2 INVALID_SCENE rejections
  (`refusing to export a disconnected world`). All four layout families appeared.
- First smoke artifacts retained at
  `/workspace/g1_failure/runtime/llm_afs_expanded/20260913T215138_375114Z`.
- Final-source smoke output directory:
  `/workspace/g1_failure/runtime/llm_afs_expanded/20260913T215450_699605Z`.
- Each valid export regenerates and verifies SceneGraph/map/XML bundle identity and
  hashes, plus preview/terrain-map PNG output. No robot rollout, paid API request,
  new video or GIF was generated during this work.

## Tool/skill handling

OpenAI docs skill used for structured Responses request integration; local provider
and existing tests were inspected first. Strict structured-output documentation was
checked at https://developers.openai.com/api/docs/guides/structured-outputs. The v2
prompt is separate because v1 forbids seed/order changes. No key was requested or saved.

The existing environment still rejects apply_patch Update File reads via bwrap user
namespace restrictions. New-file Add File succeeded. Iteration was limited to files
created by this turn using apply_patch Add File, plus normal Ruff formatting. No
preexisting user/central source file was replaced; no container security setting was
changed. Shell checks/tests used the approved escalated execution mechanism.

## Explicit limitations / next work

- These are candidate scene spaces, not proven additional robot failure mechanisms.
  GPT model performance and actual G1 outcomes require a subsequent measured campaign.
- `--samples` is an attempt budget; invalids/duplicates are retained without resampling.
  This is not yet an equal-valid-rollout autonomous comparison runner.
- Revision-level deduplication does not remove identical geometry with different seeds
  or cluster semantically identical failures. No cross-round invalid-attempt memory.
- Direct per-object pose/rotation mutation, arbitrary maze topology, dynamic obstacles,
  cross-slopes, sensor errors and robot dynamics perturbations are not implemented here.
- Terrain bundles still go only to the isolated terrain runner, never legacy registration.
- Next step: review chosen domains and execute matched robot-condition campaigns,
  comparing unique failure categories/coverage as well as raw failures, with equal
  valid-rollout budgets and multiple seeds. User supplies API key separately.
