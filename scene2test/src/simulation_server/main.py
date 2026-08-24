from __future__ import annotations

import math
from typing import Annotated

from fastapi import BackgroundTasks, Depends, FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse

from failure_client.contracts import (
    CancelResult,
    CapabilityLimits,
    CapabilitySnapshot,
    OperationCapability,
    QueryCapability,
    RecordingChannelCapability,
    RolloutRequest,
    SceneQueryRequest,
    SceneQueryResult,
)

from .bootstrap import bootstrap_groot_registry
from .config import ServerConfig
from .jobs import JobError, JobStore
from .registry import ManifestRegistry, RegistryError


def create_app(config: ServerConfig | None = None) -> FastAPI:
    settings = config or ServerConfig.from_env()
    settings.prepare()
    bootstrap_groot_registry(settings)
    registry = ManifestRegistry(settings.data_root / "registries")
    jobs = JobStore(settings)
    app = FastAPI(title="Failure-Seeking Simulation Execution Server", version="0.1.0")
    app.state.config, app.state.registry, app.state.jobs = settings, registry, jobs

    def authorize(authorization: Annotated[str | None, Header()] = None) -> None:
        if settings.api_key and authorization != f"Bearer {settings.api_key}":
            raise JobError("UNAUTHORIZED", "valid bearer token required", 401)

    secured = [Depends(authorize)]

    @app.exception_handler(JobError)
    async def job_error(_: Request, exc: JobError) -> JSONResponse:
        return _error(exc.status_code, exc.code, str(exc), retryable=exc.retryable)

    @app.exception_handler(RegistryError)
    async def registry_error(_: Request, exc: RegistryError) -> JSONResponse:
        return _error(404, "RESOURCE_REVISION_NOT_FOUND", str(exc))

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        return _error(
            422,
            "CONTRACT_VALIDATION_ERROR",
            "request does not match contract",
            {"issues": exc.errors()},
        )

    @app.get("/api/v1/health")
    def health() -> dict:
        return {
            "status": "ok",
            "execution_backend": settings.execution_backend,
            "groot_root_available": settings.groot_root.is_dir(),
        }

    @app.get("/api/v1/capabilities", dependencies=secured)
    def capabilities() -> CapabilitySnapshot:
        snapshot = registry.snapshot()
        return CapabilitySnapshot(
            registry_revision=snapshot.registry_revision,
            scene_queries=[
                QueryCapability(query_id=value, version="1.0", schema={"type": "object"})
                for value in ("get_scene_summary", "list_objects", "get_object_pose", "get_aabb")
            ],
            intervention_operations=[
                OperationCapability(
                    operation_id="set_robot_spawn",
                    version="1.0",
                    phase="PRE_RESET",
                    schema={"type": "object"},
                )
            ],
            recording_channels=[
                RecordingChannelCapability(
                    channel_id="state_trajectory", fields=["time_s", "qpos", "qvel"]
                ),
                RecordingChannelCapability(
                    channel_id="action_trajectory", fields=["time_s", "ctrl"]
                ),
                RecordingChannelCapability(
                    channel_id="contacts", fields=["time_s", "geom1", "geom2", "position_m"]
                ),
            ],
            artifact_formats=[
                {"kind": "state_trajectory", "formats": ["jsonl"]},
                {"kind": "reproduction_manifest", "formats": ["json"]},
            ],
            robots=[{"id": entry.id, "revision": entry.revision} for entry in snapshot.robots],
            controllers=[
                {"id": entry.id, "revision": entry.revision} for entry in snapshot.controllers
            ],
            policies=[{"id": entry.id, "revision": entry.revision} for entry in snapshot.policies],
            tasks=[{"id": entry.id, "revision": entry.revision} for entry in snapshot.tasks],
            limits=CapabilityLimits(
                maximum_episode_duration_s=settings.maximum_episode_duration_s,
                maximum_interventions=settings.maximum_interventions,
                maximum_parallel_jobs=1,
            ),
        )

    @app.get("/api/v1/registry/snapshot", dependencies=secured)
    def registry_snapshot():
        return registry.snapshot()

    @app.get("/api/v1/scenes/{scene_id}/snapshot", dependencies=secured)
    def scene_snapshot(scene_id: str, revision: str):
        return registry.scene_snapshot(scene_id, revision)

    @app.post("/api/v1/scenes/{scene_id}/queries", dependencies=secured)
    def scene_query(scene_id: str, query: SceneQueryRequest) -> SceneQueryResult:
        if query.scene.id != scene_id:
            raise JobError("RESOURCE_ID_MISMATCH", "path and request scene IDs differ", 422)
        snapshot = registry.scene_snapshot(scene_id, query.scene.revision)
        objects = snapshot.objects
        if query.query_id == "get_scene_summary":
            result = {"bounds": snapshot.bounds, "object_count": len(objects)}
        elif query.query_id == "list_objects":
            result = {"objects": objects}
        elif query.query_id in {"get_object_pose", "get_aabb"}:
            object_id = query.parameters.get("object_id")
            item = next((obj for obj in objects if obj.get("id") == object_id), None)
            if item is None:
                raise JobError("SCENE_OBJECT_NOT_FOUND", f"object {object_id!r} was not found", 404)
            key = "pose" if query.query_id == "get_object_pose" else "aabb"
            result = {"object_id": object_id, key: item.get(key)}
        else:
            raise JobError("QUERY_NOT_SUPPORTED", f"unsupported query: {query.query_id}", 422)
        return SceneQueryResult(
            scene=query.scene,
            query_id=query.query_id,
            query_implementation_version="manifest-1.0",
            result=result,
        )

    @app.post("/api/v1/rollouts", status_code=202, dependencies=secured)
    def submit_rollout(
        request: RolloutRequest,
        background: BackgroundTasks,
        idempotency_key: Annotated[str | None, Header()] = None,
    ):
        if not idempotency_key:
            raise JobError("IDEMPOTENCY_KEY_REQUIRED", "Idempotency-Key header is required", 400)
        _validate_rollout(request, registry, settings)
        accepted = jobs.submit(request, idempotency_key)
        if accepted.status == "QUEUED":
            background.add_task(jobs.run, accepted.job_id)
        return accepted

    @app.get("/api/v1/rollouts/{job_id}", dependencies=secured)
    def rollout_status(job_id: str):
        return jobs.status(job_id)

    @app.get("/api/v1/rollouts/{job_id}/result", dependencies=secured)
    def rollout_result(job_id: str):
        return jobs.result(job_id)

    @app.post("/api/v1/rollouts/{job_id}/cancel", dependencies=secured)
    def cancel_rollout(job_id: str) -> CancelResult:
        return CancelResult(job_id=job_id, status=jobs.cancel(job_id))

    @app.get("/api/v1/artifacts/{artifact_id:path}", dependencies=secured)
    def artifact(artifact_id: str):
        return FileResponse(jobs.artifact_path(artifact_id), filename=artifact_id.split(":", 1)[-1])

    return app


def _validate_rollout(
    request: RolloutRequest, registry: ManifestRegistry, settings: ServerConfig
) -> None:
    if request.execution.maximum_duration_s > settings.maximum_episode_duration_s:
        raise JobError("EXECUTION_LIMIT_EXCEEDED", "maximum duration exceeds server limit", 422)
    if len(request.interventions) > settings.maximum_interventions:
        raise JobError("INTERVENTION_LIMIT_EXCEEDED", "too many interventions", 422)
    resources = request.resources
    registry.resolve("scenes", resources.scene.id, resources.scene.revision)
    robot = registry.resolve("robots", resources.robot.id, resources.robot.revision)
    if resources.robot.profile_id not in robot.get("compatibility", {}).get("profile_ids", []):
        raise JobError("ROBOT_PROFILE_NOT_FOUND", "robot profile is not registered", 422)
    registry.resolve("controllers", resources.controller.id, resources.controller.revision)
    if resources.policy:
        registry.resolve("policies", resources.policy.id, resources.policy.revision)
    if request.task.schema_id.split("@", 1)[0] != "stand":
        raise JobError(
            "TASK_NOT_SUPPORTED", "only stand@1.0 is supported by this vertical slice", 422
        )
    for operation in request.interventions:
        canonical_spawn = operation.kind == "robot_initial_state.set_spawn"
        legacy_spawn = (
            operation.operation_id == "set_robot_spawn"
            and operation.kind == "robot_initial_state"
        )
        if not (canonical_spawn or legacy_spawn):
            raise JobError(
                "UNSUPPORTED_INTERVENTION", f"unsupported intervention kind: {operation.kind}", 422
            )
        position = operation.parameters.get("position_m")
        quaternion = operation.parameters.get("quaternion_wxyz")
        if position is not None and not _finite_vector(position, 3):
            raise JobError("INVALID_INTERVENTION", "position_m must be three finite numbers", 422)
        if quaternion is not None and (
            not _finite_vector(quaternion, 4)
            or math.sqrt(sum(float(value) ** 2 for value in quaternion)) < 1e-9
        ):
            raise JobError(
                "INVALID_INTERVENTION",
                "quaternion_wxyz must contain four finite values with nonzero norm",
                422,
            )


def _finite_vector(value: object, length: int) -> bool:
    return (
        isinstance(value, list)
        and len(value) == length
        and all(
            isinstance(item, (int, float))
            and not isinstance(item, bool)
            and math.isfinite(float(item))
            for item in value
        )
    )


def _error(
    status: int, code: str, message: str, details: dict | None = None, *, retryable: bool = False
) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={
            "schema_version": "1.0",
            "error": {
                "code": code,
                "message": message,
                "retryable": retryable,
                "details": details or {},
            },
        },
    )
