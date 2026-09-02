"""Fail-closed preflight for an external RoboTwin 2.0 runtime.

This module uses only the Python standard library.  It never imports RoboTwin,
SAPIEN, or Torch into the PAOS process; all runtime probes execute through the
profile-selected RoboTwin interpreter.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class PreflightConfig:
    runtime_root: Path
    runtime_python: Path
    task_name: str = "beat_block_hammer"
    task_config: str = "demo_clean"
    embodiment: str = "aloha-agilex"
    timeout_s: float = 30.0


@dataclass(frozen=True)
class PreflightCheck:
    name: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class PreflightReport:
    runtime_root: str
    runtime_python: str
    checks: tuple[PreflightCheck, ...]

    @property
    def ready(self) -> bool:
        return bool(self.checks) and all(check.passed for check in self.checks)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ready": self.ready,
            "runtime_root": self.runtime_root,
            "runtime_python": self.runtime_python,
            "checks": [asdict(check) for check in self.checks],
        }


CommandRunner = Callable[[Sequence[str], Path, float], subprocess.CompletedProcess[str]]

_ASSET_DIRS = ("background_texture", "embodiments", "objects")
_RUNTIME_MODULES = (
    "cv2",
    "gymnasium",
    "h5py",
    "imageio",
    "mplib",
    "msgpack",
    "numpy",
    "open3d",
    "pydantic",
    "sapien",
    "scipy",
    "torch",
    "transforms3d",
    "trimesh",
    "websockets",
    "yaml",
    "zarr",
)
_FULL_RUNTIME_MODULES = ("curobo", "pytorch3d", "warp")


def _default_runner(
    command: Sequence[str], cwd: Path, timeout_s: float
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(command),
        cwd=cwd,
        capture_output=True,
        check=False,
        text=True,
        timeout=timeout_s,
    )


def _command_check(
    name: str,
    command: Sequence[str],
    *,
    cwd: Path,
    timeout_s: float,
    runner: CommandRunner,
) -> PreflightCheck:
    try:
        result = runner(command, cwd, timeout_s)
    except (OSError, subprocess.SubprocessError) as exc:
        return PreflightCheck(name, False, f"{type(exc).__name__}: {exc}")
    output = "\n".join(part.strip() for part in (result.stdout, result.stderr) if part.strip())
    detail = output[-4000:] if output else f"exit={result.returncode}"
    return PreflightCheck(name, result.returncode == 0, detail)


def _layout_checks(config: PreflightConfig) -> list[PreflightCheck]:
    root = config.runtime_root
    checks = [
        PreflightCheck("runtime_root", root.is_dir(), str(root)),
        PreflightCheck(
            "runtime_python",
            config.runtime_python.is_file(),
            str(config.runtime_python),
        ),
    ]
    required_files = (
        Path("scripts/collect_data.py"),
        Path("envs/_base_task.py"),
        Path(f"env_cfg/task_config/{config.task_config}.yml"),
        Path("env_cfg/task_config/_embodiment_config.yml"),
    )
    for relative in required_files:
        path = root / relative
        checks.append(PreflightCheck(f"file:{relative}", path.is_file(), str(path)))
    for name in _ASSET_DIRS:
        asset_dir = root / "assets" / name
        count = sum(1 for item in asset_dir.rglob("*") if item.is_file()) if asset_dir.is_dir() else 0
        checks.append(
            PreflightCheck(
                f"asset:{name}",
                count > 0,
                f"{asset_dir} files={count}",
            )
        )
    embodiment_config = root / "assets" / "embodiments" / config.embodiment / "config.yml"
    checks.append(
        PreflightCheck(
            "embodiment_config",
            embodiment_config.is_file(),
            str(embodiment_config),
        )
    )
    return checks


def run_preflight(
    config: PreflightConfig,
    *,
    runner: CommandRunner = _default_runner,
) -> PreflightReport:
    root = config.runtime_root.expanduser().resolve()
    runtime_python = config.runtime_python.expanduser().resolve()
    normalized = PreflightConfig(
        runtime_root=root,
        runtime_python=runtime_python,
        task_name=config.task_name,
        task_config=config.task_config,
        embodiment=config.embodiment,
        timeout_s=config.timeout_s,
    )
    checks = _layout_checks(normalized)
    if not root.is_dir() or not runtime_python.is_file():
        return PreflightReport(str(root), str(runtime_python), tuple(checks))

    python = str(runtime_python)
    module_probe = (
        "import importlib.util,json,sys;"
        f"names={list(_RUNTIME_MODULES + _FULL_RUNTIME_MODULES)!r};"
        "missing=[n for n in names if importlib.util.find_spec(n) is None];"
        "print(json.dumps({'python':sys.version.split()[0],'missing':missing}));"
        "raise SystemExit(bool(missing))"
    )
    checks.append(
        _command_check(
            "runtime_modules",
            (python, "-c", module_probe),
            cwd=root,
            timeout_s=normalized.timeout_s,
            runner=runner,
        )
    )

    xpolicylab_probe = (
        "import importlib.metadata as m,json;"
        "print(json.dumps({'xpolicylab':m.version('xpolicylab')}))"
    )
    checks.append(
        _command_check(
            "xpolicylab_install",
            (python, "-c", xpolicylab_probe),
            cwd=root,
            timeout_s=normalized.timeout_s,
            runner=runner,
        )
    )

    cuda_probe = (
        "import json,torch;"
        "device=torch.cuda.get_device_name(0);cap=torch.cuda.get_device_capability(0);"
        "value=(torch.tensor([1.0],device='cuda')+1).cpu().item();"
        "print(json.dumps({'device':device,'capability':cap,'value':value,'torch':torch.__version__}))"
    )
    checks.append(
        _command_check(
            "torch_cuda_kernel",
            (python, "-c", cuda_probe),
            cwd=root,
            timeout_s=normalized.timeout_s,
            runner=runner,
        )
    )

    renderer_probe = (
        "import sapien.core as sapien;"
        "engine=sapien.Engine();renderer=sapien.SapienRenderer();"
        "engine.set_renderer(renderer);engine.create_scene();print('sapien_renderer_scene=ok')"
    )
    checks.append(
        _command_check(
            "sapien_renderer",
            (python, "-c", renderer_probe),
            cwd=root,
            timeout_s=normalized.timeout_s,
            runner=runner,
        )
    )

    task_probe = (
        "from scripts.collect_data import class_decorator;"
        f"task=class_decorator({normalized.task_name!r});"
        "print(type(task).__module__+'.'+type(task).__name__);"
        "assert not hasattr(task,'scene')"
    )
    checks.append(
        _command_check(
            "task_import_no_setup",
            (python, "-c", task_probe),
            cwd=root,
            timeout_s=normalized.timeout_s,
            runner=runner,
        )
    )

    checks.append(
        _command_check(
            "vulkan_device",
            ("vulkaninfo", "--summary"),
            cwd=root,
            timeout_s=normalized.timeout_s,
            runner=runner,
        )
    )
    return PreflightReport(str(root), str(runtime_python), tuple(checks))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate an external RoboTwin 2.0 runtime")
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--runtime-python", type=Path, required=True)
    parser.add_argument("--task-name", default="beat_block_hammer")
    parser.add_argument("--task-config", default="demo_clean")
    parser.add_argument("--embodiment", default="aloha-agilex")
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args(argv)
    report = run_preflight(
        PreflightConfig(
            runtime_root=args.runtime_root,
            runtime_python=args.runtime_python,
            task_name=args.task_name,
            task_config=args.task_config,
            embodiment=args.embodiment,
            timeout_s=args.timeout,
        )
    )
    print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
    return 0 if report.ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
