"""Scene-only adapter: never accept planner, task or robot changes from AFS."""

from clear_path.contracts import Fixture


def validate_scene(value=None):
    config = Fixture() if value is None else Fixture.model_validate(value)
    baseline = Fixture()
    for key in ("footprint_radius_m", "clearance_m"):
        if getattr(config, key) != getattr(baseline, key):
            raise ValueError(f"AFS cannot change robot planner field: {key}")
    return config
