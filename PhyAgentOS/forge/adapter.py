"""Normalize one Forge Gateway session into execution and evidence contracts."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from PhyAgentOS.config.schema import ForgeConfig
from PhyAgentOS.forge.client import ForgeGatewayClient, ForgeGatewayError
from PhyAgentOS.forge.evidence import ForgeEvidenceWriter
from PhyAgentOS.forge.observation import (
    ForgeObservationCollector,
    ForgeObservationError,
    ObservationSnapshot,
)
from PhyAgentOS.verification.contracts import (
    EvidenceBundle,
    ExecutionError,
    ExecutionRecord,
    ExecutionTimeline,
    ForgeSessionRecord,
    utc_now,
)

FORGE_GATEWAY_API_VERSION = "paos-forge-gateway-mvp-plus.v1"
TERMINAL_GATEWAY_STATUSES = {"succeeded", "failed", "cancelled"}
AdapterEvent = Callable[[str, dict[str, Any]], Awaitable[None]]


@dataclass(frozen=True)
class ForgeAdapterOutcome:
    execution: ExecutionRecord
    evidence: EvidenceBundle | None
    evidence_bundle_ref: str | None
    create_response: dict[str, Any] | None
    last_response: dict[str, Any] | None
    cancel_response: dict[str, Any] | None


class ForgeAdapter:
    def __init__(
        self,
        *,
        workspace: str | Path,
        config: ForgeConfig,
        client: ForgeGatewayClient,
        collector_factory=ForgeObservationCollector,
    ) -> None:
        self.workspace = Path(workspace).expanduser().resolve()
        self.config = config
        self.client = client
        self.collector_factory = collector_factory

    async def capabilities(self) -> dict[str, Any]:
        return self.validate_capabilities(await self.client.capabilities())

    def validate_capabilities(self, response: dict[str, Any]) -> dict[str, Any]:
        data = self._data(response)
        version = data.get("api_version")
        if version != FORGE_GATEWAY_API_VERSION or version != self.config.api_version:
            raise ForgeGatewayError(
                "FORGE_GATEWAY_API_UNSUPPORTED: expected "
                f"{FORGE_GATEWAY_API_VERSION}, got {version!r}"
            )
        supports = data.get("supports")
        required = ("sessions", "command_id", "runtime_context", "serial_actions_only")
        if not isinstance(supports, dict) or any(supports.get(key) is not True for key in required):
            raise ForgeGatewayError(
                "FORGE_GATEWAY_CAPABILITY_MISSING: sessions, command_id, runtime_context, "
                "and serial_actions_only are required"
            )
        if not isinstance(data.get("actions"), dict):
            raise ForgeGatewayError("FORGE_GATEWAY_CAPABILITY_INVALID: actions must be an object")
        return data

    async def run(
        self,
        record: ForgeSessionRecord,
        *,
        capabilities: dict[str, Any],
        resume: bool,
        on_event: AdapterEvent,
    ) -> ForgeAdapterOutcome:
        request = record.request
        action_capability = capabilities["actions"].get(request.action_type)
        if not isinstance(action_capability, dict):
            raise ForgeGatewayError(f"FORGE_ACTION_UNSUPPORTED: {request.action_type}")
        payload = {
            "session_id": record.session_id,
            "command_id": record.command_id,
            "action_type": request.action_type,
            "instruction": request.task_description,
            "source": request.source,
            "inputs": dict(request.inputs),
        }
        writer = ForgeEvidenceWriter(self.workspace, record.session_id, record.command_id)
        verification_enabled = request.verification.mode != "off"
        required_kinds = list(request.verification.evidence_policy.required_kinds)
        required_sources: list[str] = []
        collector: ForgeObservationCollector | None = None
        before: ObservationSnapshot | None = None
        before_ref = record.before_snapshot_ref
        after_ref: str | None = None
        errors: list[str] = []
        terminal_observed_at: datetime | None = None
        create_response: dict[str, Any] | None = record.gateway_create_response
        last_response: dict[str, Any] | None = record.gateway_last_response
        cancel_response: dict[str, Any] | None = None
        gateway_status = "unknown"
        execution_error: ExecutionError | None = None

        if verification_enabled:
            if request.verification.evidence_policy.minimum_association == "authoritative":
                raise ForgeGatewayError(
                    "FORGE_EVIDENCE_ASSOCIATION_UNSUPPORTED: Gateway 1.0 evidence is best_effort"
                )
            required_sources = await self._required_image_sources(record)
            collector = self.collector_factory(
                self.config.base_url,
                required_image_sources=required_sources,
                max_artifact_bytes=self.config.evidence.max_artifact_bytes,
                require_state="robot_state" in required_kinds,
                connection_timeout_s=self.config.evidence.connection_timeout_s,
            )
            await collector.start()

        try:
            if resume:
                if before_ref:
                    try:
                        before = writer.load_snapshot(before_ref)
                    except Exception as exc:
                        errors.append(f"persisted before snapshot unavailable: {exc}")
                try:
                    last_response = await self.client.get_session(record.session_id)
                except ForgeGatewayError as exc:
                    if exc.status_code == 404:
                        raise ForgeGatewayError(
                            "FORGE_EXECUTION_STATE_LOST: dispatched session is absent from Gateway",
                            status_code=404,
                        ) from exc
                    raise
                await on_event("running", {"last_response": last_response, "resumed": True})
            else:
                if collector is not None:
                    await on_event("capturing_before", {})
                    try:
                        before = await collector.wait_for_before(
                            self.config.evidence.capture_timeout_s
                        )
                        before_ref = writer.write_snapshot("before", before)
                        await on_event("before_captured", {"before_snapshot_ref": before_ref})
                    except ForgeObservationError as exc:
                        errors.append(str(exc))
                        if request.verification.mode != "audit":
                            raise ForgeGatewayError(str(exc)) from exc
                await on_event("dispatching", {"payload": payload})
                create_response = await self.client.create_session(payload)
                last_response = create_response
                session_data, command_data = self._validated_session_command(
                    create_response, record.session_id, record.command_id
                )
                self._validate_action_identity(
                    session_data, command_data, payload, action_capability
                )
                await on_event(
                    "running",
                    {"create_response": create_response, "last_response": create_response},
                )

            deadline = asyncio.get_running_loop().time() + request.execution_timeout_s
            while True:
                if last_response is None:
                    last_response = await self.client.get_session(record.session_id)
                session_data, command_data = self._validated_session_command(
                    last_response, record.session_id, record.command_id
                )
                self._validate_action_identity(
                    session_data, command_data, payload, action_capability
                )
                gateway_status = str(session_data.get("status") or "unknown")
                command_status = str(command_data.get("status") or "unknown")
                if gateway_status in TERMINAL_GATEWAY_STATUSES:
                    if command_status != gateway_status:
                        raise ForgeGatewayError(
                            "Gateway session/command terminal status does not match"
                        )
                    terminal_observed_at = utc_now()
                    break
                if asyncio.get_running_loop().time() >= deadline:
                    gateway_status = "timed_out"
                    terminal_observed_at = utc_now()
                    execution_error = ExecutionError(
                        code="GATEWAY_EXECUTION_TIMEOUT",
                        message=(
                            "Forge Gateway session exceeded execution_timeout_s="
                            f"{request.execution_timeout_s}"
                        ),
                    )
                    try:
                        cancel_response = await self.client.cancel_session(
                            record.session_id, "execution timeout"
                        )
                    except Exception as exc:
                        cancel_response = {"ok": False, "error": str(exc)}
                    break
                await asyncio.sleep(self.config.poll_interval_s)
                last_response = await self.client.get_session(record.session_id)

            await on_event(
                "finalizing",
                {
                    "last_response": last_response,
                    "cancel_response": cancel_response,
                    "gateway_status": gateway_status,
                },
            )
            if collector is not None and terminal_observed_at is not None:
                if before is None and before_ref:
                    try:
                        before = writer.load_snapshot(before_ref)
                    except Exception as exc:
                        errors.append(f"persisted before snapshot unavailable: {exc}")
                if before is not None:
                    try:
                        after = await collector.wait_for_after(
                            before,
                            terminal_observed_at=terminal_observed_at,
                            timeout_s=self.config.evidence.post_capture_timeout_s,
                        )
                        after_ref = writer.write_snapshot("after", after)
                    except ForgeObservationError as exc:
                        errors.append(str(exc))
        finally:
            if collector is not None:
                errors.extend(collector.errors)
                await collector.close()

        session_data, command_data = self._last_known_session_command(
            last_response or {}, record.session_id, record.command_id
        )
        if execution_error is None and gateway_status == "failed":
            execution_error = ExecutionError(
                code="GATEWAY_SESSION_FAILED",
                message=str(command_data.get("message") or session_data.get("message") or ""),
            )
        execution = ExecutionRecord(
            session_id=record.session_id,
            command_id=record.command_id,
            gateway_api_version=str(capabilities["api_version"]),
            gateway_instance_id=self._gateway_instance_id(capabilities),
            action_type=request.action_type,
            policy_id=str(action_capability.get("policy_id") or "") or None,
            status=(
                gateway_status
                if gateway_status
                in {
                    "queued",
                    "sent",
                    "running",
                    "succeeded",
                    "failed",
                    "timed_out",
                    "cancelled",
                }
                else "unknown"
            ),
            result_semantics=str(
                action_capability.get("result_semantics") or "command_completed"
            ),
            completion=(
                dict(action_capability.get("completion"))
                if isinstance(action_capability.get("completion"), dict)
                else {}
            ),
            timeline=ExecutionTimeline(
                created_at=self._float_or_none(session_data.get("created_at")),
                updated_at=self._float_or_none(session_data.get("updated_at")),
                sent_at=self._float_or_none(command_data.get("sent_at")),
                terminal_observed_at=terminal_observed_at,
            ),
            outputs=(
                dict(command_data.get("outputs"))
                if isinstance(command_data.get("outputs"), dict)
                else {}
            ),
            error=execution_error,
        )
        persisted_execution = writer.load_execution()
        if persisted_execution is not None:
            expected_identity = (
                execution.session_id,
                execution.command_id,
                execution.gateway_api_version,
                execution.action_type,
            )
            actual_identity = (
                persisted_execution.session_id,
                persisted_execution.command_id,
                persisted_execution.gateway_api_version,
                persisted_execution.action_type,
            )
            if actual_identity != expected_identity:
                raise ForgeGatewayError(
                    "persisted Execution Record identity does not match Gateway session"
                )
            execution = persisted_execution
        else:
            writer.write_execution(execution)
        evidence: EvidenceBundle | None = None
        evidence_ref: str | None = None
        if verification_enabled:
            evidence, evidence_ref = writer.write_bundle(
                before_ref=before_ref,
                after_ref=after_ref,
                terminal_observed_at=terminal_observed_at,
                required_sources=required_sources,
                required_kinds=required_kinds,
                errors=errors,
            )
        return ForgeAdapterOutcome(
            execution,
            evidence,
            evidence_ref,
            create_response,
            last_response,
            cancel_response,
        )

    async def _required_image_sources(self, record: ForgeSessionRecord) -> list[str]:
        policy_sources = record.request.verification.evidence_policy.required_sources
        if policy_sources:
            return list(dict.fromkeys(policy_sources))
        if self.config.evidence.required_image_sources:
            return list(dict.fromkeys(self.config.evidence.required_image_sources))
        context = self._data(await self.client.runtime_context())
        readiness = context.get("readiness") if isinstance(context.get("readiness"), dict) else {}
        images = readiness.get("images") if isinstance(readiness.get("images"), dict) else {}
        sources = [str(source) for source in images]
        if not sources:
            raise ForgeGatewayError(
                "FORGE_EVIDENCE_CONFIGURATION_REQUIRED: configure forge.evidence.requiredImageSources"
            )
        return sources

    def _validated_session_command(
        self, response: dict[str, Any], session_id: str, command_id: str
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        session, command = self._last_known_session_command(response, session_id, command_id)
        if session.get("session_id") != session_id:
            raise ForgeGatewayError("Gateway response session_id does not match request")
        if command.get("command_id") != command_id:
            raise ForgeGatewayError("Gateway response command_id does not match request")
        if command.get("session_id") != session_id:
            raise ForgeGatewayError("Gateway command belongs to another session")
        if command.get("request_id") != command_id:
            raise ForgeGatewayError("Gateway command request_id does not match command_id")
        return session, command

    def _last_known_session_command(
        self, response: dict[str, Any], session_id: str, command_id: str
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        data = self._data(response)
        session = data.get("session") if isinstance(data.get("session"), dict) else {}
        candidates: list[dict[str, Any]] = []
        if isinstance(data.get("command"), dict):
            candidates.append(data["command"])
        if isinstance(data.get("commands"), list):
            candidates.extend(item for item in data["commands"] if isinstance(item, dict))
        command = next(
            (item for item in candidates if item.get("command_id") == command_id),
            candidates[0] if len(candidates) == 1 else {},
        )
        return dict(session), dict(command)

    @staticmethod
    def _validate_action_identity(
        session: dict[str, Any],
        command: dict[str, Any],
        payload: dict[str, Any],
        capability: dict[str, Any],
    ) -> None:
        if session.get("action_type") != payload["action_type"]:
            raise ForgeGatewayError(
                "Gateway session action_type does not match the requested action"
            )
        expected = {
            "action_type": payload["action_type"],
            "policy_id": capability.get("policy_id"),
            "command": capability.get("command"),
        }
        for field, value in expected.items():
            if value is not None and command.get(field) != value:
                raise ForgeGatewayError(
                    f"Gateway command {field} does not match advertised action capability"
                )

    @staticmethod
    def _data(response: dict[str, Any]) -> dict[str, Any]:
        data = response.get("data")
        return dict(data) if isinstance(data, dict) else dict(response)

    @staticmethod
    def _float_or_none(value: Any) -> float | None:
        try:
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _gateway_instance_id(capabilities: dict[str, Any]) -> str | None:
        value = capabilities.get("gateway_instance_id") or capabilities.get("instance_id")
        return str(value) if value else None
