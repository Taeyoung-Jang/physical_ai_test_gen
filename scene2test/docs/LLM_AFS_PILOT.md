# GPT-6 AFS: bounded terrain-space proposal pilot

2026-09-13. This is an initial implementation, **not evidence of GPT-6 search superiority**.
The role is a failure-space proposer, not a calibrated numeric surrogate or a robot VLM.
Existing ExtraTrees/Panda methods and common server workers are unchanged.

## What is implemented

- GPT-6 Astra (`gpt-6-astra`) Responses API request with strict JSON-schema output.
- Input: generated SceneGraph/SceneSpec, task endpoints, robot/policy/observation specs,
  allowed parameter domains, fixed fields, previous verified rollout observations.
- Output: hypothesized failure space (a subset of allowed paths and narrowed ranges),
  textual hypothesis, 1–8 representatives. No arbitrary code, XML or new field paths.
- Independent validation rejects extra fields, nonfinite numbers, unknown/duplicate
  paths, changed base revisions and representatives outside declared ranges.
- Representatives and optional Sobol samples generate immutable actual terrain bundles.
  Geometry checks preserve endpoints and require a static path. Invalid scenes and
  duplicates are recorded; no silent resampling, no claims they are robot failures.
- Explicit local feedback import validates prior context/suite, scene bundle,
  request/task settings, result artifacts, actual scene, CUDA provider, and consistent
  worker/resource versions. Actual results enter the next prompt, predictions do not.
- Request/response/proposal/status/context/code hashes are saved. API usage and response
  model/id remain in api_response.json. Credentials and Authorization headers are not saved.

This is a **manual-round local pilot**: it prepares one request or makes at most one API
call, creates scenes, then exits. It does not auto-launch GPUs, submit terrain to the
legacy server, run until a valid-rollout budget is reached, or add a failure_client plugin.

## Start without an API key

Run from `scene2test`, using the existing dependencies (`httpx`, `pydantic`, etc.).
No new SDK install or pyproject/lockfile change is required.

```bash
# Default is request preparation ONLY, even if a key exists in the environment.
PYTHONPATH=src .venv/bin/python tools/run_llm_afs.py

# Deterministic fixture -> real generated scenes, no API or GPU call.
PYTHONPATH=src .venv/bin/python tools/run_llm_afs.py --offline-demo --samples 2
```

The default config is `config/llm_afs_terrain.yaml`: one ramp, three continuous
parameters (angle, surface friction, corridor width), fixed seed/segment layout and
fixed GT-navigation/GR00T policy. These ranges are initial engineering choices, not
measured robot capability limits. Edit the YAML to define a different supported course.

Outputs default to `/workspace/g1_failure/runtime/llm_afs/<unique timestamp>/`.
`--output-root` selects another parent; each invocation creates a new directory.
Offline output is explicitly marked `offline_fixture`; it must never be reported as a
GPT-6-generated result or as evidence of adaptive performance.

## Enable the API later

Set OPENAI_API_KEY in your own terminal/secret manager. Do not put it in YAML, source,
chat, Git, or a command argument. Review context.json before sending: it contains scene,
robot/policy/task descriptions and selected past metrics, not local media files.

Then explicitly opt in:

```bash
PYTHONPATH=src .venv/bin/python tools/run_llm_afs.py --live --samples 2
```

The endpoint is fixed to `https://api.openai.com/v1/responses`; redirects are not followed.
One invocation makes at most one attempt, with no automatic retries. Default timeout
is 120 seconds and output cap is 4096 tokens including reasoning; `--max-output-tokens`
accepts 512–16384. Model/reasoning defaults are GPT-6 Astra / medium, with `store: false`.
This storage setting is not a claim of zero retention under every provider policy.
Input context is capped at 250 KB (bytes, NOT tokens). These limits are not a currency
budget and do not guarantee a complete response. Refusals/incomplete outputs stop the run.
API access, billing, latency and actual GPT-6 schema acceptance require a live validation
after the user supplies a key; no such live validation was performed for this implementation.

To regenerate scenes from a previously saved proposal without another API call:

```bash
PYTHONPATH=src .venv/bin/python tools/run_llm_afs.py \
  --proposal-file /ABS/PREVIOUS_RUN/proposal.json --samples 2 --seed 0
```

This avoids a repeat paid call; it is not in-place resume or exactly-once remote billing.
A timeout may leave an unknown remote outcome. Inspect saved artifacts before retrying.

## Execute scenes separately, then feed actual results back

Only after reviewing the generated suite, run the existing isolated runner explicitly:

```bash
PYTHONPATH=src .venv/bin/python tools/run_terrain_validation.py \
  --suite /ABS/LLM_RUN/suite.json --duration 120 --speed 0.25
```

Duration/speed must match task_spec. That runner records videos, GIFs, trajectories,
contacts and reproduction metadata in a separate timestamped terrain_validation run.
No server registration is involved. A successful scene export is not robot traversability.

For the next proposal round:

```bash
PYTHONPATH=src .venv/bin/python tools/run_llm_afs.py --live \
  --feedback /ABS/LLM_RUN /ABS/TERRAIN_RUN/summary.json
```

The previous run's observation history is carried forward and newly imported actual
results are appended. Pass the immediately previous proposal run and its runner summary.
Maximum accumulated observations is 64; exceeding it fails rather than silently
truncating. Duplicate job imports, changed config, changed worker/resource identity or
artifact mismatch are rejected. Repeated scene executions are separate observations,
not automatically unique failures. Invalid executions and infra errors remain separate.
This checks trusted local records for accidental mismatch, not cryptographic authenticity
against a malicious writer able to replace the manifests themselves.

The metadata fields keep map/localization/VLM concepts separate for future expansion,
but v1 deliberately accepts only the existing GT terrain execution condition. Setting
`robot_vlm_enabled: true` or visual localization in YAML does not implement that robot
policy and is rejected. No GPT-6 robot control, SLAM, lighting mutations, integer topology
mutations, arbitrary mesh upload or automatic segment-order changes are implemented.

## Limits and next steps

- No autonomous experiment scheduler or equal-valid-budget comparison is implemented.
- No calibrated failure probability, LLM training or measured adaptive gain is claimed.
- Parameter spaces are continuous scalar subsets of existing recipe fields. Changes
  that move generated spawn/goal are rejected. Some combinations can remain invalid
  despite valid individual parameter ranges and are logged as INVALID_SCENE.
- Proposal ranges are candidate spaces, not proven failure regions. Explanations are
  hypotheses and do not replace independent outcome evaluation.
- The sampler seed fixes local scene sampling, not nondeterminism of external API calls.
- First finish live API acceptance and a manually driven feedback round. Then extend
  history selection, budgeted orchestration and fair baseline comparisons as separate work.

Sources consulted for request construction:
[GPT-6 Astra](https://developers.openai.com/api/docs/models/gpt-6-astra),
[Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs).

Design background: [LLM-first discussion](AFS_LLM_FIRST_DESIGN.md).
