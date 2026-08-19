"""Unit tests for scene_adapter.py's scoped yaml.safe_load patch (blueprint §14.2 — must never
write to disk, must be a no-op unless explicitly opted into via env var).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import pytest
import yaml

from g1_local_nav.scene_adapter import DEFAULT_TARGET_SCENE_PATH, SCENE_OVERRIDE_ENV_VAR, scene_override

TEST_YAML = 'ROBOT_SCENE: "assets/scene_43dof.xml"\nOTHER: 42\n'


@pytest.fixture(autouse=True)
def _clean_env():
    os.environ.pop(SCENE_OVERRIDE_ENV_VAR, None)
    yield
    os.environ.pop(SCENE_OVERRIDE_ENV_VAR, None)


def test_noop_when_env_var_unset():
    with scene_override():
        result = yaml.safe_load(TEST_YAML)
    assert result["ROBOT_SCENE"] == "assets/scene_43dof.xml"


def test_patches_to_default_target_scene_when_env_var_set_to_1():
    os.environ[SCENE_OVERRIDE_ENV_VAR] = "1"
    with scene_override():
        result = yaml.safe_load(TEST_YAML)
    assert result["ROBOT_SCENE"] == str(DEFAULT_TARGET_SCENE_PATH)
    assert result["OTHER"] == 42  # other keys pass through untouched


def test_patches_to_explicit_path_when_env_var_set(tmp_path: Path):
    custom = tmp_path / "custom_scene.xml"
    custom.write_text("<mujoco/>")
    os.environ[SCENE_OVERRIDE_ENV_VAR] = str(custom)
    with scene_override():
        result = yaml.safe_load(TEST_YAML)
    assert result["ROBOT_SCENE"] == str(custom)


def test_missing_scene_file_raises(tmp_path: Path):
    os.environ[SCENE_OVERRIDE_ENV_VAR] = str(tmp_path / "does_not_exist.xml")
    with pytest.raises(FileNotFoundError):
        with scene_override():
            pass


def test_patch_reverts_after_context_exits():
    os.environ[SCENE_OVERRIDE_ENV_VAR] = "1"
    with scene_override():
        pass
    result = yaml.safe_load(TEST_YAML)  # outside the context now
    assert result["ROBOT_SCENE"] == "assets/scene_43dof.xml"


def test_patch_reverts_even_on_exception():
    os.environ[SCENE_OVERRIDE_ENV_VAR] = "1"
    with pytest.raises(RuntimeError):
        with scene_override():
            raise RuntimeError("boom")
    result = yaml.safe_load(TEST_YAML)
    assert result["ROBOT_SCENE"] == "assets/scene_43dof.xml"


def test_no_file_written_to_disk(tmp_path: Path, monkeypatch):
    # Sanity check that scene_override() only touches yaml.safe_load's return value — never
    # opens ROBOT_SCENE's original file path for writing.
    original_open = open
    write_attempts = []

    def guarded_open(path, mode="r", *args, **kwargs):
        if "w" in mode or "a" in mode:
            write_attempts.append(str(path))
        return original_open(path, mode, *args, **kwargs)

    monkeypatch.setattr("builtins.open", guarded_open)
    os.environ[SCENE_OVERRIDE_ENV_VAR] = "1"
    with scene_override():
        yaml.safe_load(TEST_YAML)
    assert write_attempts == []


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
