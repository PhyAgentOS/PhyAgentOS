from __future__ import annotations

import json
from pathlib import Path, PurePosixPath

import yaml
from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).parents[1]
INDEX_PATH = ROOT / "docs/forge/paos-forge-packages.yaml"
SCHEMA_PATH = ROOT / "docs/forge/paos-forge-packages.schema.json"

EXPECTED_EXECUTABLES = {
    "gateway",
    "relative_pose_policy",
    "gripper_action_policy",
    "motion_action_policy",
    "motion_server",
    "joint_trajectory_controller",
    "gripper_action_controller",
    "mujoco_sim",
    "image_viewer",
}


def _index() -> dict:
    return yaml.safe_load(INDEX_PATH.read_text(encoding="utf-8"))


def test_forge_package_index_matches_schema() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema, format_checker=FormatChecker())

    validator.validate(_index())


def test_forge_package_identities_and_bundle_fields_are_complete() -> None:
    packages = _index()["packages"]
    identities = [
        (item["package_key"], item["version"], item["platform"], item["arch"])
        for item in packages
    ]

    assert len(identities) == len(set(identities))
    by_kind = {
        kind: [item for item in packages if item["kind"] == kind]
        for kind in {item["kind"] for item in packages}
    }
    assert set(by_kind) == {"skill_bundle", "node_bundle"}

    skill = by_kind["skill_bundle"][0]
    assert {"skill.yaml", "SKILL.md"} <= {item["path"] for item in skill["inventory"]}
    assert len(skill["dependencies"]) == len(by_kind["node_bundle"])
    assert {item["artifact_id"] for item in by_kind["node_bundle"]} == set(
        skill["dependencies"]
    )


def test_node_inventories_are_safe_and_cover_skill_binaries() -> None:
    nodes = [item for item in _index()["packages"] if item["kind"] == "node_bundle"]
    executable_paths = set()
    for node in nodes:
        assert node["install_root"].startswith("~/.PhyAgentOS/forge_runtime/nodes/")
        for item in node["inventory"]:
            path = PurePosixPath(item["path"])
            assert not path.is_absolute()
            assert item["path"] not in {"", "."}
            assert ".." not in path.parts
            assert "\\" not in item["path"]
            if item["category"] == "executable":
                executable_paths.add(item["path"])
    assert executable_paths == EXPECTED_EXECUTABLES


def test_release_locations_are_https_or_explicit_todos() -> None:
    for package in _index()["packages"]:
        for field in ("backend_url", "direct_download_url"):
            value = package[field]
            assert value is None or value.startswith("https://")
        if package["backend_url"] is None and package["direct_download_url"] is None:
            assert package["todos"]
        assert package["archive"] == {"format": "tar.gz"}
