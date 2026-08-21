# Failure Client implementation guide

이 package는 MacBook에서 연구 실험을 제어하고 외부 RunPod Simulation Server에
rollout을 요청하는 Client control plane이다. MuJoCo/G1 runtime이나 GPU worker는 이
저장소에서 실행하지 않는다.

## 실행 준비

```bash
cd scene2test
uv sync

export FAILURE_CLIENT_SERVER_URL="https://your-runpod-server.example"
export FAILURE_CLIENT_TOKEN="..."              # Server가 요구할 때만
export FAILURE_CLIENT_WORKSPACE="./workspace"
```

Token은 protocol, lock, SQLite, export에 저장되지 않는다. 모든 실험 resource는
Server registry가 반환한 immutable revision으로 고정해야 한다.

## 명령

```bash
failure-client health
failure-client registry-sync
failure-client method-list
failure-client validate config/failure_client_example.yaml
failure-client run config/failure_client_example.yaml
failure-client resume config/failure_client_example.yaml
failure-client export exp_g1_nav_failure_001
failure-client reevaluate exp_g1_nav_failure_001 new_failure_definition.yaml
```

`run`은 새 experiment만 만든다. 같은 ID가 이미 있으면 실패하며, 중단된 실험은
반드시 `resume`으로 이어간다. Client는 POST 전에 canonical request hash와
idempotency key를 SQLite에 commit하므로 submit 응답을 저장하기 전에 종료돼도 같은
remote job을 회수한다.

## 저장 결과

- `workspace/client.sqlite`: registry revision, candidate, request/result hash, evaluation,
  archive, method checkpoint
- `workspace/artifacts/`: SHA-256 content-addressed artifact
- `workspace/experiments/<id>/protocol.lock.yaml`: immutable protocol/capability provenance
- `workspace/experiments/<id>/exports/`: confirmed failure reproduction manifest

Raw `RolloutResult`와 Client의 `ResearchEvaluation`은 별도 레코드다. 동일한 raw result는
새 `FailureDefinition`으로 append-only 재평가할 수 있고, invalid execution과
infrastructure error는 failure-rate 분모에 포함되지 않는다.

## Method 확장과 기존 코드 경계

Built-in method는 `random_parametric`, `sobol_parametric`, `manual`이다.
`legacy_afs_import`와 `legacy_lam_guided_import`는 기존 AFS/LAM 코드나 로컬 PyBullet
oracle을 호출하지 않는다. 기존 pipeline이 내보낸 mutation/case record를 generic
intervention으로 변환하여 동일한 RunPod gateway/evaluator/archive 경로에서 재실행하는
migration bridge다.

외부 package는 `failure_client.methods` Python entry-point에 factory를 등록하면 Core
수정 없이 로드된다. 모든 method는 requirements, deterministic propose/observe,
RNG를 포함한 state checkpoint 계약을 구현해야 한다.

## 검증

```bash
uv run ruff check src/failure_client tests/client
uv run pytest tests/client -q
```

Local suite는 golden contract, fake gateway, crash recovery, checksum 재다운로드,
Random/Sobol 교체, branch provenance, versioned 재평가와 100-rollout orchestration을
검증한다. 실제 RunPod smoke/integration은 Server URL, token, READY resource revision과
비용 승인이 있는 환경에서 별도로 실행해야 한다.
