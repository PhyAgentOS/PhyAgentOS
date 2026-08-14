"""Explicit lifecycle manager for local Forge Skill runtimes."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from PhyAgentOS.config.paths import (
    get_forge_runtime_root,
    get_skill_runtime_logs_dir,
)
from PhyAgentOS.skill_runtime.catalog import SkillCatalog
from PhyAgentOS.skill_runtime.manifest import RuntimeProfile, SkillManifest
from PhyAgentOS.skill_runtime.state import RuntimeState, RuntimeStateStore, utc_now


class RuntimeManagerError(RuntimeError):
    """Raised when a managed Skill lifecycle operation cannot complete."""


@dataclass(frozen=True)
class RuntimeStatusReport:
    """Persisted and live status reconciled at query time."""

    state: RuntimeState | None
    flow_running: bool
    gateway_ready: bool
    tool_contexts: dict[str, bool]

    @property
    def ready(self) -> bool:
        return (
            self.state is not None
            and self.state.status == "running"
            and self.flow_running
            and self.gateway_ready
            and all(self.tool_contexts.values())
        )


class RuntimeManager:
    """Start and stop named Dora dataflows for installed Skill bundles."""

    def __init__(
        self,
        *,
        catalog: SkillCatalog | None = None,
        state_store: RuntimeStateStore | None = None,
        runtime_root: Path | None = None,
        logs_root: Path | None = None,
        health_timeout_s: float = 30.0,
        poll_interval_s: float = 0.25,
    ) -> None:
        self.catalog = catalog or SkillCatalog()
        self.state_store = state_store or RuntimeStateStore()
        self.runtime_root = (runtime_root or get_forge_runtime_root()).expanduser().resolve()
        self.logs_root = (logs_root or get_skill_runtime_logs_dir()).expanduser()
        self.health_timeout_s = health_timeout_s
        self.poll_interval_s = poll_interval_s

    @staticmethod
    def flow_name(skill_name: str, profile: str) -> str:
        safe = f"paos-{skill_name}-{profile}"
        if not safe.replace("-", "").replace("_", "").isalnum():
            raise RuntimeManagerError("Skill and profile names must be Dora-name safe")
        return safe

    def start(self, skill_name: str, profile_name: str) -> RuntimeState:
        manifest = self.catalog.get(skill_name)
        profile = manifest.profiles.get(profile_name)
        if profile is None:
            available = ", ".join(sorted(manifest.profiles))
            raise RuntimeManagerError(
                f"Unknown profile {profile_name!r}; available profiles: {available}"
            )
        flow_name = self.flow_name(skill_name, profile_name)
        previous = self.state_store.load(skill_name)
        if (
            previous is not None
            and previous.profile == profile_name
            and previous.status in {"starting", "running"}
        ):
            report = self.status(skill_name)
            if report.ready:
                return report.state  # type: ignore[return-value]

        self._preflight(profile)
        if self._gateway_snapshot(manifest) is not None:
            raise RuntimeManagerError(
                f"Gateway address {manifest.gateway_url} is already in use; "
                "refusing to adopt an unmanaged runtime"
            )

        starting = RuntimeState(
            skill_name=skill_name,
            profile=profile_name,
            status="starting",
            flow_name=flow_name,
            gateway_url=manifest.gateway_url,
            started_at=utc_now(),
        )
        self.state_store.save(starting)
        self._log(skill_name, f"starting profile={profile_name} flow={flow_name}")
        launched = False
        try:
            self._ensure_dora_up(profile)
            launched = True
            self._start_flow(flow_name, profile)
            self._wait_until_ready(manifest, flow_name)
            running = starting.with_status("running")
            self.state_store.save(running)
            self._log(skill_name, "runtime ready")
            return running
        except Exception as exc:
            message = self._safe_error(exc)
            if launched:
                self._stop_flow(flow_name, force=True, check=False)
            failed = starting.with_status("failed", error=message)
            self.state_store.save(failed)
            self._log(skill_name, f"startup failed: {message}")
            if isinstance(exc, RuntimeManagerError):
                raise
            raise RuntimeManagerError(message) from exc

    def status(self, skill_name: str) -> RuntimeStatusReport:
        manifest = self.catalog.get(skill_name)
        state = self.state_store.load(skill_name)
        if state is None:
            return RuntimeStatusReport(None, False, False, {})
        flow_running = self._flow_running(state.flow_name)
        snapshot = self._gateway_snapshot(manifest)
        contexts = self._tool_context_readiness(manifest) if snapshot is not None else {}
        gateway_ready = snapshot is not None
        live_ready = flow_running and gateway_ready and all(
            contexts.get(tool_id, False) for tool_id in manifest.required_tools
        )
        reconciled = state
        if live_ready and state.status in {"starting", "running", "failed"}:
            reconciled = state.with_status("running")
        elif state.status == "stopping" and not flow_running:
            reconciled = state.with_status("stopped", active_invocations=())
        elif state.status in {"starting", "running"} and not live_ready:
            reasons = []
            if not flow_running:
                reasons.append("Dora flow is not running")
            if not gateway_ready:
                reasons.append("Gateway GET /tools is unavailable")
            missing = [tool for tool in manifest.required_tools if not contexts.get(tool, False)]
            if missing and gateway_ready:
                reasons.append(f"Tool context is not ready: {', '.join(missing)}")
            reconciled = state.with_status("failed", error="; ".join(reasons))
        if reconciled != state:
            self.state_store.save(reconciled)
        return RuntimeStatusReport(reconciled, flow_running, gateway_ready, contexts)

    def stop(self, skill_name: str, *, force: bool = False) -> RuntimeState:
        self.catalog.get(skill_name)
        state = self.state_store.load(skill_name)
        if state is None:
            raise RuntimeManagerError(f"Skill {skill_name!r} has no runtime state")
        if state.status == "stopped" and not self._flow_running(state.flow_name):
            return state
        if state.active_invocations and not force:
            raise RuntimeManagerError(
                "Runtime has non-terminal Tool invocation(s); reconcile or cancel them "
                "before stopping, or pass --force"
            )
        stopping = state.with_status("stopping")
        self.state_store.save(stopping)
        self._log(skill_name, f"stopping flow={state.flow_name} force={force}")
        try:
            self._stop_flow(state.flow_name, force=force)
        except Exception as exc:
            message = self._safe_error(exc)
            failed = stopping.with_status("failed", error=message)
            self.state_store.save(failed)
            self._log(skill_name, f"stop failed: {message}")
            if isinstance(exc, RuntimeManagerError):
                raise
            raise RuntimeManagerError(message) from exc
        stopped = stopping.with_status("stopped", active_invocations=())
        self.state_store.save(stopped)
        self._log(skill_name, "runtime stopped")
        return stopped

    def read_logs(self, skill_name: str, *, lines: int = 200) -> str:
        self.catalog.get(skill_name)
        if lines < 1:
            raise RuntimeManagerError("lines must be positive")
        path = self.logs_root / f"{skill_name}.log"
        state = self.state_store.load(skill_name)
        launch_path = (
            None
            if state is None
            else self.logs_root / f"{state.flow_name}-dora.log"
        )
        sections = []
        if path.is_file():
            sections.append(path.read_text(encoding="utf-8"))
        if launch_path is not None and launch_path.is_file():
            sections.append(launch_path.read_text(encoding="utf-8", errors="replace"))
        combined = "".join(sections)
        return "".join(combined.splitlines(keepends=True)[-lines:])

    def _preflight(self, profile: RuntimeProfile) -> None:
        dora = shutil.which("dora")
        if dora is None:
            raise RuntimeManagerError("dora is not installed or not available on PATH")
        result = self._run([dora, "--version"], timeout=5)
        if result.returncode != 0:
            raise RuntimeManagerError("dora version check failed")
        self._runtime_path(profile.dataflow, kind="dataflow", executable=False)
        for relative in profile.required_binaries:
            self._runtime_path(relative, kind="required binary", executable=True)
        for relative in profile.required_assets:
            self._runtime_path(relative, kind="required asset", executable=False)
        missing_environment = [
            name for name in profile.required_environment if not os.environ.get(name)
        ]
        if missing_environment:
            raise RuntimeManagerError(
                f"Required environment is not configured: {', '.join(missing_environment)}"
            )

    def _runtime_path(self, relative: Path, *, kind: str, executable: bool) -> Path:
        candidate = (self.runtime_root / relative).resolve()
        if not candidate.is_relative_to(self.runtime_root):
            raise RuntimeManagerError(f"{kind} path escapes ~/.PhyAgentOS/forge_runtime")
        if not candidate.is_file():
            raise RuntimeManagerError(f"{kind} is missing: {relative.as_posix()}")
        if executable and not os.access(candidate, os.X_OK):
            raise RuntimeManagerError(f"{kind} is not executable: {relative.as_posix()}")
        return candidate

    def _ensure_dora_up(self, profile: RuntimeProfile) -> None:
        dora = shutil.which("dora")
        assert dora is not None
        cwd = self._runtime_path(profile.dataflow, kind="dataflow", executable=False).parent
        check = self._run([dora, "check"], cwd=cwd, timeout=5)
        if check.returncode == 0:
            return
        self.logs_root.mkdir(parents=True, exist_ok=True)
        coordinator_log = self.logs_root / "dora-coordinator.log"
        with coordinator_log.open("ab") as output:
            try:
                env = {
                    **os.environ,
                    **profile.environment,
                    "FORGE_RUNTIME_BIN": str(self.runtime_root),
                }
                subprocess.Popen(
                    [dora, "up"],
                    cwd=cwd,
                    env=env,
                    stdout=output,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
            except OSError as exc:
                raise RuntimeManagerError("failed to launch dora up") from exc
        deadline = time.monotonic() + min(self.health_timeout_s, 10.0)
        while time.monotonic() < deadline:
            if self._run([dora, "check"], cwd=cwd, timeout=5).returncode == 0:
                return
            time.sleep(self.poll_interval_s)
        raise RuntimeManagerError("dora up did not become ready before the timeout")

    def _start_flow(self, flow_name: str, profile: RuntimeProfile) -> None:
        dora = shutil.which("dora")
        assert dora is not None
        dataflow = self._runtime_path(profile.dataflow, kind="dataflow", executable=False)
        env = {
            **os.environ,
            **profile.environment,
            "FORGE_RUNTIME_BIN": str(self.runtime_root),
        }
        self.logs_root.mkdir(parents=True, exist_ok=True)
        launch_log = self.logs_root / f"{flow_name}-dora.log"
        with launch_log.open("ab") as output:
            try:
                process = subprocess.Popen(
                    [dora, "start", "--name", flow_name, dataflow.name],
                    cwd=dataflow.parent,
                    env=env,
                    stdin=subprocess.DEVNULL,
                    stdout=output,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
            except OSError as exc:
                raise RuntimeManagerError("failed to launch dora start") from exc
        time.sleep(min(0.25, self.poll_interval_s))
        if process.poll() not in {None, 0}:
            raise RuntimeManagerError(
                "dora start exited before the flow was admitted; inspect Skill runtime logs"
            )

    def _stop_flow(self, flow_name: str, *, force: bool, check: bool = True) -> None:
        dora = shutil.which("dora")
        if dora is None:
            raise RuntimeManagerError("dora is not installed or not available on PATH")
        command = [dora, "stop", "--name", flow_name]
        command.extend(["--force"] if force else ["--grace-duration", "5s"])
        result = self._run(command, cwd=self.runtime_root, timeout=15)
        if check and result.returncode != 0 and self._flow_running(flow_name):
            raise RuntimeManagerError("dora stop failed and the flow is still running")

    def _flow_running(self, flow_name: str) -> bool:
        dora = shutil.which("dora")
        if dora is None:
            return False
        result = self._run(
            [dora, "list", "--format", "json", "--name", flow_name],
            timeout=5,
        )
        if result.returncode != 0:
            return False
        try:
            data = json.loads(result.stdout or "[]")
        except json.JSONDecodeError:
            return flow_name in (result.stdout or "") and "running" in (
                result.stdout or ""
            ).lower()

        def has_running(value: Any) -> bool:
            if isinstance(value, dict):
                name_matches = value.get("name") in {None, flow_name}
                status = str(value.get("status", "")).lower()
                if name_matches and status == "running":
                    return True
                return any(has_running(item) for item in value.values())
            if isinstance(value, list):
                return any(has_running(item) for item in value)
            return False

        return has_running(data)

    def _wait_until_ready(self, manifest: SkillManifest, flow_name: str) -> None:
        deadline = time.monotonic() + self.health_timeout_s
        last_reason = "Gateway GET /tools is unavailable"
        while time.monotonic() < deadline:
            if not self._flow_running(flow_name):
                last_reason = "Dora flow is not running"
            elif self._gateway_snapshot(manifest) is None:
                last_reason = "Gateway GET /tools is unavailable"
            else:
                contexts = self._tool_context_readiness(manifest)
                missing = [
                    tool for tool in manifest.required_tools if not contexts.get(tool, False)
                ]
                if not missing:
                    return
                last_reason = f"Tool context is not ready: {', '.join(missing)}"
            time.sleep(self.poll_interval_s)
        raise RuntimeManagerError(f"Runtime health check timed out: {last_reason}")

    def _gateway_snapshot(self, manifest: SkillManifest) -> dict[str, Any] | None:
        try:
            value = self._get_json(f"{manifest.gateway_url}/tools")
        except RuntimeManagerError:
            return None
        return value if value.get("ok") is True else None

    def _tool_context_readiness(self, manifest: SkillManifest) -> dict[str, bool]:
        readiness: dict[str, bool] = {}
        for tool_id in manifest.required_tools:
            try:
                value = self._get_json(
                    f"{manifest.gateway_url}/tools/{quote(tool_id, safe='')}/context"
                )
                data = value.get("data", {})
                readiness[tool_id] = (
                    value.get("ok") is True
                    and isinstance(data, dict)
                    and data.get("ready") is True
                    and data.get("binding_error") is None
                )
            except RuntimeManagerError:
                readiness[tool_id] = False
        return readiness

    def _get_json(self, url: str) -> dict[str, Any]:
        request = Request(url, headers={"Accept": "application/json"})
        try:
            with urlopen(request, timeout=2.0) as response:
                if response.status != 200:
                    raise RuntimeManagerError("Gateway health request failed")
                value = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            raise RuntimeManagerError("Gateway health request failed") from exc
        if not isinstance(value, dict):
            raise RuntimeManagerError("Gateway health response must be a JSON object")
        return value

    @staticmethod
    def _run(
        command: list[str],
        *,
        cwd: Path | None = None,
        env: dict[str, str] | None = None,
        timeout: float,
    ) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(
                command,
                cwd=cwd,
                env=env,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RuntimeManagerError(f"{Path(command[0]).name} command failed") from exc

    def _log(self, skill_name: str, message: str) -> None:
        self.logs_root.mkdir(parents=True, exist_ok=True)
        with (self.logs_root / f"{skill_name}.log").open("a", encoding="utf-8") as handle:
            handle.write(f"{utc_now()} {message}\n")

    @staticmethod
    def _safe_error(error: Exception) -> str:
        if isinstance(error, RuntimeManagerError):
            return str(error)
        return f"{type(error).__name__} during runtime lifecycle operation"
