from __future__ import annotations

import subprocess
from pathlib import Path

from robotwin20_adapter.preflight import PreflightConfig, run_preflight


def runtime_layout(root: Path) -> tuple[Path, Path]:
    for relative in (
        "scripts/collect_data.py",
        "envs/_base_task.py",
        "env_cfg/task_config/demo_clean.yml",
        "env_cfg/task_config/_embodiment_config.yml",
        "assets/background_texture/example.png",
        "assets/embodiments/aloha-agilex/config.yml",
        "assets/embodiments/franka-panda/config.yml",
        "assets/objects/example/model.json",
    ):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fixture", encoding="utf-8")
    python = root / "bin/python"
    python.parent.mkdir(parents=True)
    python.write_text("fixture", encoding="utf-8")
    return root, python


def passing_runner(command, cwd, timeout):
    return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")


def test_preflight_passes_only_when_layout_and_dynamic_checks_pass(tmp_path):
    root, python = runtime_layout(tmp_path / "RoboTwin")
    report = run_preflight(
        PreflightConfig(root, python),
        runner=passing_runner,
    )
    assert report.ready is True
    assert {check.name for check in report.checks} >= {
        "asset:background_texture",
        "runtime_modules",
        "torch_cuda_kernel",
        "sapien_renderer",
        "task_import_no_setup",
        "vulkan_device",
    }


def test_preflight_fails_when_an_asset_family_is_missing(tmp_path):
    root, python = runtime_layout(tmp_path / "RoboTwin")
    (root / "assets/objects/example/model.json").unlink()
    report = run_preflight(PreflightConfig(root, python), runner=passing_runner)
    assert report.ready is False
    assert next(check for check in report.checks if check.name == "asset:objects").passed is False


def test_preflight_propagates_runtime_probe_failure_without_running_actions(tmp_path):
    root, python = runtime_layout(tmp_path / "RoboTwin")
    commands: list[str] = []

    def failing_cuda_runner(command, cwd, timeout):
        joined = " ".join(command)
        commands.append(joined)
        if "get_device_capability" in joined:
            return subprocess.CompletedProcess(command, 1, stdout="", stderr="no kernel image")
        return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

    report = run_preflight(PreflightConfig(root, python), runner=failing_cuda_runner)
    assert report.ready is False
    cuda = next(check for check in report.checks if check.name == "torch_cuda_kernel")
    assert cuda.passed is False
    assert "no kernel image" in cuda.detail
    assert all("setup_demo" not in command for command in commands)
    assert all("play_once" not in command for command in commands)
    assert all("check_success" not in command for command in commands)


def test_preflight_accepts_two_single_arm_embodiment_profile(tmp_path):
    root, python = runtime_layout(tmp_path / "RoboTwin")
    franka = root / "assets/embodiments/franka-panda/config.yml"
    franka.write_text("dual_arm: false\n", encoding="utf-8")
    report = run_preflight(
        PreflightConfig(root, python, embodiment=("franka-panda", "franka-panda", 0.8)),
        runner=passing_runner,
    )
    assert report.ready is True
    assert {check.name for check in report.checks} >= {
        "embodiment_config:franka-panda", "embodiment_topology"
    }


def test_preflight_rejects_non_finite_pair_interval(tmp_path):
    root, python = runtime_layout(tmp_path / "RoboTwin")
    report = run_preflight(
        PreflightConfig(root, python, embodiment=("aloha-agilex", "aloha-agilex", float("nan"))),
        runner=passing_runner,
    )
    assert report.ready is False
    assert report.checks[0].name == "embodiment"
