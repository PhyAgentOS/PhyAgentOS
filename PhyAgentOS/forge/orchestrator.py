"""Forge-only asynchronous execution, verification, and recovery orchestration."""

from __future__ import annotations

import asyncio
import json
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from PhyAgentOS.agent.session_verifier import ForgeTaskVerifier
from PhyAgentOS.bus.events import InboundMessage
from PhyAgentOS.bus.queue import MessageBus
from PhyAgentOS.config.schema import ForgeConfig
from PhyAgentOS.forge.adapter import ForgeAdapter, ForgeAdapterOutcome
from PhyAgentOS.forge.client import ForgeGatewayClient, ForgeGatewayError
from PhyAgentOS.forge.store import ForgeSessionStore
from PhyAgentOS.verification.contracts import (
    TERMINAL_FORGE_STATUSES,
    ExecutionError,
    ExecutionRecord,
    ExecutionTimeline,
    ForgeSessionRecord,
    ForgeSessionStatus,
    ForgeTaskRequest,
    RecoveryRequest,
    VerificationAttempt,
    utc_now,
)


class ForgeSessionOrchestrator:
    def __init__(
        self,
        *,
        workspace: str | Path,
        config: ForgeConfig,
        verifier: ForgeTaskVerifier | None,
        bus: MessageBus | None,
        max_replans: int = 2,
        replan_timeout_s: float = 120.0,
        client: ForgeGatewayClient | None = None,
        adapter: ForgeAdapter | None = None,
        store: ForgeSessionStore | None = None,
    ) -> None:
        self.workspace = Path(workspace).expanduser().resolve()
        self.config = config
        self.verifier = verifier
        self.bus = bus
        self.max_replans = max(0, int(max_replans))
        self.replan_timeout_s = max(1.0, float(replan_timeout_s))
        self.store = store or ForgeSessionStore(self.workspace)
        self.client = client or ForgeGatewayClient(
            config.base_url, timeout_s=config.request_timeout_s
        )
        self.adapter = adapter or ForgeAdapter(
            workspace=self.workspace, config=config, client=self.client
        )
        self.capabilities: dict[str, Any] | None = None
        self.verifier_error: str | None = None
        self._tasks: dict[str, asyncio.Task] = {}
        self._verification_locks: dict[str, asyncio.Lock] = {}
        self._start_lock = asyncio.Lock()
        self._started = False
        self._stopping = False
        self._stopped = asyncio.Event()

    async def start(self) -> None:
        async with self._start_lock:
            if self._started:
                return
            if not self.config.enabled:
                self._started = True
                return
            self.capabilities = await self.adapter.capabilities()
            if self.verifier is not None:
                try:
                    await self.verifier.start()
                except Exception as exc:
                    self.verifier_error = str(exc) or type(exc).__name__
            for record in self.store.nonterminal():
                if record.status == ForgeSessionStatus.VERIFYING:
                    self.store.update(
                        record.session_id,
                        self._abandon_verification,
                        event_type="verification_abandoned_on_restart",
                    )
                self._schedule(record.session_id)
            self._started = True

    async def run(self) -> None:
        await self.start()
        if not self.config.enabled:
            await self._stopped.wait()
            return
        try:
            while not self._stopping:
                await self._expire_replans()
                await asyncio.sleep(0.5)
        finally:
            self._stopped.set()

    async def stop(self) -> None:
        if self._stopping:
            return
        self._stopping = True
        if self.config.enabled:
            for record in self.store.nonterminal():
                await self.cancel_session(record.session_id, reason="paos_shutdown")
        for task in list(self._tasks.values()):
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks.values(), return_exceptions=True)
        self._tasks.clear()
        if self.verifier is not None:
            self.verifier.stop()
        await self.client.close()
        self._stopped.set()

    async def submit(
        self,
        request: ForgeTaskRequest,
        *,
        channel: str = "cli",
        chat_id: str = "direct",
        session_key: str | None = None,
    ) -> ForgeSessionRecord:
        self._require_enabled()
        await self.start()
        self._require_verifier(request)
        actions = self.capabilities.get("actions", {}) if self.capabilities else {}
        if not isinstance(actions.get(request.action_type), dict):
            raise ValueError(
                f"Forge Gateway does not advertise action {request.action_type!r}"
            )
        session_id = f"forge_{uuid4().hex[:16]}"
        command_id = f"command_{uuid4().hex[:16]}"
        record = ForgeSessionRecord(
            session_id=session_id,
            command_id=command_id,
            root_session_id=session_id,
            request=request,
            origin_channel=channel,
            origin_chat_id=chat_id,
            origin_session_key=session_key,
        )
        self.store.create(record)
        self._schedule(record.session_id)
        return record

    async def create_replanned(
        self,
        parent_session_id: str,
        *,
        task_description: str,
        action_type: str,
        inputs: dict[str, Any],
        execution_timeout_s: float | None = None,
    ) -> ForgeSessionRecord:
        parent = self.store.get(parent_session_id)
        if parent.status != ForgeSessionStatus.AWAITING_REPLAN:
            raise ValueError("parent session is not awaiting replan")
        recovery = parent.recovery_request
        if recovery is None or utc_now() >= recovery.deadline:
            raise ValueError("recovery request is absent or expired")
        if parent.replan_attempt >= self.max_replans:
            raise ValueError(f"replan budget exhausted ({self.max_replans})")
        request = ForgeTaskRequest(
            task_description=task_description,
            action_type=action_type,
            inputs=inputs,
            verification=parent.request.verification.model_copy(deep=True),
            execution_timeout_s=(
                execution_timeout_s
                if execution_timeout_s is not None
                else parent.request.execution_timeout_s
            ),
            source=parent.request.source,
        )
        child_id = f"forge_{uuid4().hex[:16]}"
        child = ForgeSessionRecord(
            session_id=child_id,
            command_id=f"command_{uuid4().hex[:16]}",
            root_session_id=parent.root_session_id,
            parent_session_id=parent.session_id,
            replan_attempt=parent.replan_attempt + 1,
            request=request,
            origin_channel=parent.origin_channel,
            origin_chat_id=parent.origin_chat_id,
            origin_session_key=parent.origin_session_key,
        )
        _, child = self.store.create_replanned(parent_session_id, child)
        self._schedule(child.session_id)
        return child

    def get_session(self, session_id: str) -> ForgeSessionRecord:
        return self.store.get(session_id)

    async def cancel_session(
        self, session_id: str, *, reason: str = "paos_requested"
    ) -> ForgeSessionRecord:
        record = self.store.get(session_id)
        if record.status in TERMINAL_FORGE_STATUSES:
            return record
        task = self._tasks.get(session_id)
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        record = self.store.get(session_id)
        if record.status in TERMINAL_FORGE_STATUSES:
            return record
        cancel_response: dict[str, Any] | None = None
        if record.dispatch_attempted_at is not None:
            try:
                cancel_response = await self.client.cancel_session(session_id, reason)
            except Exception as exc:
                cancel_response = {"ok": False, "error": str(exc)}

        def mutate(current: ForgeSessionRecord) -> None:
            current.status = ForgeSessionStatus.CANCELLED
            current.gateway_cancel_response = cancel_response
            current.error_code = "FORGE_SESSION_CANCELLED"
            current.error_message = reason

        result = self.store.update(
            session_id,
            mutate,
            event_type="session_cancelled",
            payload={"reason": reason, "gateway": cancel_response},
        )
        await self._notify_terminal(result)
        return result

    async def get_context(self) -> dict[str, Any]:
        self._require_enabled()
        await self.start()
        status, context = await asyncio.gather(
            self.client.runtime_status(), self.client.runtime_context()
        )
        return {
            "gateway": {
                "base_url": self.config.base_url,
                "api_version": self.config.api_version,
            },
            "capabilities": self.capabilities,
            "status": self._response_data(status),
            "context": self._response_data(context),
        }

    async def reset(self, inputs: dict[str, Any] | None = None) -> dict[str, Any]:
        self._require_enabled()
        await self.start()
        if self.store.nonterminal():
            raise RuntimeError("cannot reset Forge while a task lineage is active")
        return await self.client.reset_runtime(inputs)

    async def review(self, session_id: str) -> ForgeSessionRecord:
        record = self.store.get(session_id)
        if record.status not in TERMINAL_FORGE_STATUSES:
            raise ValueError("Forge session is not terminal")
        if self.verifier is None or self.verifier_error:
            raise RuntimeError(self.verifier_error or "semantic verifier is disabled")
        lock = self._verification_locks.setdefault(session_id, asyncio.Lock())
        async with lock:
            record = self.store.get(session_id)
            verdict, _, attempt = await self.verifier.verify(
                record,
                history=self.store.events(record.root_session_id),
                lessons=self._lessons(),
                source="tool",
                mode="review",
            )

            def mutate(current: ForgeSessionRecord) -> None:
                current.verification.attempts.append(attempt)
                current.verification.verdict = verdict

            record = self.store.update(
                session_id, mutate, event_type="verification_reviewed"
            )
            self.verifier.write_verification_result(record)
            return record

    async def wait_for_lineage(
        self, root_session_id: str, *, timeout_s: float | None = None
    ) -> ForgeSessionRecord:
        async def wait() -> ForgeSessionRecord:
            while True:
                lineage = self.store.lineage(root_session_id)
                active = [item for item in lineage if item.status not in TERMINAL_FORGE_STATUSES]
                if not active:
                    return lineage[-1]
                await asyncio.sleep(0.1)

        return await asyncio.wait_for(wait(), timeout_s) if timeout_s else await wait()

    def capabilities_summary(self) -> str:
        if not self.config.enabled:
            return "Forge execution is disabled."
        if self.capabilities is None:
            return "Forge capabilities have not been loaded yet."
        actions = self.capabilities.get("actions", {})
        lines = [
            "Forge Gateway is the only robot execution path.",
            f"API: {self.capabilities.get('api_version')}",
            "Actions:",
        ]
        for name, capability in sorted(actions.items()):
            if not isinstance(capability, dict):
                continue
            required = capability.get("required_parameters", [])
            mapping = capability.get("input_mapping", {})
            description = str(capability.get("description") or "").strip()
            detail = f"required inputs={required}; input mapping={mapping}"
            if description:
                detail += f"; {description}"
            lines.append(f"- {name}: {detail}")
        return "\n".join(lines)

    def _schedule(self, session_id: str) -> None:
        current = self._tasks.get(session_id)
        if current is not None and not current.done():
            return
        task = asyncio.create_task(self._process(session_id), name=f"forge-session-{session_id}")
        self._tasks[session_id] = task
        task.add_done_callback(lambda done, sid=session_id: self._task_finished(sid, done))

    def _task_finished(self, session_id: str, task: asyncio.Task) -> None:
        if self._tasks.get(session_id) is task:
            self._tasks.pop(session_id, None)
        if not task.cancelled():
            try:
                task.exception()
            except Exception:
                pass

    async def _process(self, session_id: str) -> None:
        try:
            while not self._stopping:
                record = self.store.get(session_id)
                if record.status in TERMINAL_FORGE_STATUSES:
                    return
                if record.status in {
                    ForgeSessionStatus.ACCEPTED,
                    ForgeSessionStatus.CAPTURING_BEFORE,
                    ForgeSessionStatus.DISPATCHING,
                    ForgeSessionStatus.RUNNING,
                    ForgeSessionStatus.FINALIZING,
                }:
                    await self._execute(record)
                    continue
                if record.status in {
                    ForgeSessionStatus.AWAITING_VERIFICATION,
                    ForgeSessionStatus.VERIFYING,
                }:
                    await self._verify(record)
                    continue
                if record.status == ForgeSessionStatus.AWAITING_REPLAN:
                    await self._dispatch_recovery(record)
                    return
                raise RuntimeError(f"unsupported Forge orchestration state: {record.status}")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            record = self.store.get(session_id)
            if record.status not in TERMINAL_FORGE_STATUSES:
                await self._fail(record, exc)

    async def _execute(self, record: ForgeSessionRecord) -> None:
        if self.capabilities is None:
            raise RuntimeError("Forge capabilities are unavailable")
        resume = record.dispatch_attempted_at is not None

        async def on_event(event: str, payload: dict[str, Any]) -> None:
            def mutate(current: ForgeSessionRecord) -> None:
                if event == "capturing_before" and current.status == ForgeSessionStatus.ACCEPTED:
                    current.status = ForgeSessionStatus.CAPTURING_BEFORE
                elif event == "before_captured":
                    current.before_snapshot_ref = payload["before_snapshot_ref"]
                elif event == "dispatching":
                    current.status = ForgeSessionStatus.DISPATCHING
                    current.dispatch_attempted_at = utc_now()
                elif event == "running":
                    if current.status != ForgeSessionStatus.FINALIZING:
                        current.status = ForgeSessionStatus.RUNNING
                    current.gateway_create_response = payload.get(
                        "create_response", current.gateway_create_response
                    )
                    current.gateway_last_response = payload.get(
                        "last_response", current.gateway_last_response
                    )
                elif event == "finalizing":
                    current.status = ForgeSessionStatus.FINALIZING
                    current.gateway_last_response = payload.get("last_response")
                    current.gateway_cancel_response = payload.get("cancel_response")

            self.store.update(
                record.session_id,
                mutate,
                event_type=f"adapter_{event}",
                payload={key: value for key, value in payload.items() if key != "payload"},
            )

        outcome = await self.adapter.run(
            record,
            capabilities=self.capabilities,
            resume=resume,
            on_event=on_event,
        )
        self._store_outcome(record.session_id, outcome)
        current = self.store.get(record.session_id)
        if current.request.verification.mode == "off":
            current = self._finish_from_execution(current)
            await self._notify_terminal(current)
        else:
            def awaiting(current_record: ForgeSessionRecord) -> None:
                current_record.status = ForgeSessionStatus.AWAITING_VERIFICATION
                current_record.verification.status = "pending"

            self.store.update(
                record.session_id,
                awaiting,
                event_type="awaiting_verification",
            )

    def _store_outcome(self, session_id: str, outcome: ForgeAdapterOutcome) -> None:
        def mutate(record: ForgeSessionRecord) -> None:
            record.status = ForgeSessionStatus.FINALIZING
            record.execution = outcome.execution
            record.gateway_create_response = outcome.create_response
            record.gateway_last_response = outcome.last_response
            record.gateway_cancel_response = outcome.cancel_response
            record.verification.bundle_ref = outcome.evidence_bundle_ref

        self.store.update(session_id, mutate, event_type="execution_recorded")

    def _finish_from_execution(self, record: ForgeSessionRecord) -> ForgeSessionRecord:
        if record.execution is None:
            raise RuntimeError("cannot finalize Forge session without Execution Record")
        mapping = {
            "succeeded": ForgeSessionStatus.SUCCEEDED,
            "failed": ForgeSessionStatus.FAILED,
            "timed_out": ForgeSessionStatus.TIMED_OUT,
            "cancelled": ForgeSessionStatus.CANCELLED,
        }
        status = mapping.get(record.execution.status, ForgeSessionStatus.FAILED)

        def mutate(current: ForgeSessionRecord) -> None:
            current.status = status
            if status != ForgeSessionStatus.SUCCEEDED and current.execution is not None:
                current.error_code, current.error_message = (
                    self._execution_error_details(current)
                )

        return self.store.update(record.session_id, mutate, event_type="execution_finalized")

    async def _verify(self, record: ForgeSessionRecord) -> None:
        if self.verifier is None or self.verifier_error:
            await self._verification_error(
                record,
                "VERIFICATION_SERVICE_UNAVAILABLE",
                self.verifier_error or "semantic verifier is disabled",
            )
            return

        def mark_running(current: ForgeSessionRecord) -> None:
            current.status = ForgeSessionStatus.VERIFYING
            current.verification.status = "running"

        record = self.store.update(
            record.session_id, mark_running, event_type="verification_started"
        )
        try:
            verdict, request, attempt = await self.verifier.verify(
                record,
                history=self.store.events(record.root_session_id),
                lessons=self._lessons(),
            )
        except Exception as exc:
            await self._verification_error(
                record,
                self._verification_error_code(exc),
                str(exc) or type(exc).__name__,
            )
            return

        mode = record.request.verification.mode
        if mode == "audit":
            final_status = self._status_from_execution(record)
        elif verdict.verdict == "success":
            final_status = ForgeSessionStatus.SUCCEEDED
        elif verdict.verdict == "replan_required" and mode == "recovery":
            if record.replan_attempt >= self.max_replans:
                await self._verification_error(
                    record,
                    "VERIFICATION_REPLAN_LIMIT_REACHED",
                    f"replan limit reached ({self.max_replans}): {verdict.reason}",
                    attempt=attempt,
                    verdict=verdict,
                )
                return
            final_status = ForgeSessionStatus.AWAITING_REPLAN
        else:
            final_status = ForgeSessionStatus.FAILED

        recovery_request = None
        if final_status == ForgeSessionStatus.AWAITING_REPLAN:
            unmet = [item.criterion for item in verdict.criteria if item.status != "satisfied"]
            context = verdict.recovery_context
            if context is not None:
                unmet.extend(context.unmet_criteria)
            constraints = list(record.request.verification.constraints)
            if context is not None:
                constraints.extend(context.preserved_constraints)
            refs = list(verdict.evidence_refs)
            for criterion in verdict.criteria:
                refs.extend(criterion.evidence_refs)
            recovery_request = RecoveryRequest(
                request_id=f"recovery_{uuid4().hex[:16]}",
                parent_session_id=record.session_id,
                unmet_criteria=list(dict.fromkeys(unmet)),
                preserved_constraints=list(dict.fromkeys(constraints)),
                guidance=context.guidance if context is not None else verdict.reason,
                evidence_refs=list(dict.fromkeys(refs)),
                deadline=utc_now() + timedelta(seconds=self.replan_timeout_s),
            )

        def finish(current: ForgeSessionRecord) -> None:
            current.status = final_status
            current.verification.status = "completed"
            current.verification.verdict = verdict
            current.verification.attempts.append(attempt)
            current.recovery_request = recovery_request
            if mode == "audit" and final_status != ForgeSessionStatus.SUCCEEDED:
                current.error_code, current.error_message = (
                    self._execution_error_details(current)
                )
            elif final_status == ForgeSessionStatus.FAILED:
                current.error_code = (
                    "VERIFICATION_REPLAN_REQUIRED"
                    if verdict.verdict == "replan_required"
                    else "VERIFICATION_INCONCLUSIVE"
                    if verdict.verdict == "inconclusive"
                    else "VERIFICATION_FAILED"
                )
                current.error_message = verdict.reason

        record = self.store.update(
            record.session_id, finish, event_type="verification_completed"
        )
        retention = self.verifier.apply_retention(
            request, final_status=final_status.value
        )
        record = self.store.update(
            record.session_id,
            lambda current: setattr(current.verification, "retention", retention),
            event_type="evidence_retention_applied",
        )
        self.verifier.write_verification_result(record)
        self.verifier.write_lesson(
            record,
            summary=verdict.lesson,
            phase="forge_verification",
            error_code=record.error_code,
        )
        if final_status != ForgeSessionStatus.AWAITING_REPLAN:
            await self._notify_terminal(record)

    async def _verification_error(
        self,
        record: ForgeSessionRecord,
        code: str,
        message: str,
        *,
        attempt: VerificationAttempt | None = None,
        verdict=None,
    ) -> None:
        mode = record.request.verification.mode
        final_status = (
            self._status_from_execution(record)
            if mode == "audit"
            else ForgeSessionStatus.FAILED
        )
        failed_attempt = attempt or VerificationAttempt(
            attempt_id=f"verification_{uuid4().hex[:12]}", error=message
        )

        def mutate(current: ForgeSessionRecord) -> None:
            current.status = final_status
            current.verification.status = "error"
            current.verification.error = message
            current.verification.attempts.append(failed_attempt)
            if verdict is not None:
                current.verification.verdict = verdict
            if mode == "audit" and final_status != ForgeSessionStatus.SUCCEEDED:
                current.error_code, current.error_message = (
                    self._execution_error_details(current)
                )
            elif mode != "audit":
                current.error_code = code
                current.error_message = message

        record = self.store.update(
            record.session_id, mutate, event_type="verification_failed"
        )
        if self.verifier is not None:
            self.verifier.write_verification_result(record)
            self.verifier.write_lesson(
                record,
                summary=message,
                phase="forge_verification",
                error_code=code,
            )
        await self._notify_terminal(record)

    async def _dispatch_recovery(self, record: ForgeSessionRecord) -> None:
        request = record.recovery_request
        if request is None:
            await self._fail(record, RuntimeError("awaiting_replan has no RecoveryRequest"))
            return
        if utc_now() >= request.deadline:
            await self._fail(
                record,
                RuntimeError("Agent Planner did not create a recovery child before the deadline"),
                code="VERIFICATION_REPLAN_TIMEOUT",
            )
            return
        if self.bus is None:
            return
        payload = {
            "parent_session_id": record.session_id,
            "goal": record.request.verification.goal,
            "success_criteria": record.request.verification.success_criteria,
            "constraints": request.preserved_constraints,
            "unmet_criteria": request.unmet_criteria,
            "reason_and_guidance": request.guidance,
            "evidence_refs": request.evidence_refs,
            "deadline": request.deadline.isoformat(),
        }
        await self.bus.publish_inbound(
            InboundMessage(
                channel="system",
                sender_id="forge-verifier",
                chat_id=f"{record.origin_channel}:{record.origin_chat_id}",
                session_key_override=record.origin_session_key,
                content=(
                    "[System: Forge task recovery requested]\n"
                    "Re-plan through the normal Planner. Preserve the goal, constraints, and "
                    "verification contract. Call create_replanned_forge_session exactly once with "
                    "a newly planned action_type, inputs, and task_description. Never reuse an old "
                    "command ID and do not treat verifier guidance as an executable command.\n\n"
                    + json.dumps(payload, ensure_ascii=False, indent=2)
                ),
                metadata={"recovery_request_id": request.request_id},
            )
        )

        def mark_dispatched(current: ForgeSessionRecord) -> None:
            if current.recovery_request is not None:
                current.recovery_request.dispatched_at = utc_now()

        self.store.update(
            record.session_id,
            mark_dispatched,
            event_type="recovery_dispatched",
        )

    async def _expire_replans(self) -> None:
        for record in self.store.nonterminal():
            if (
                record.status == ForgeSessionStatus.AWAITING_REPLAN
                and record.recovery_request is not None
                and utc_now() >= record.recovery_request.deadline
            ):
                await self._fail(
                    record,
                    RuntimeError(
                        "Agent Planner did not create a recovery child before the deadline"
                    ),
                    code="VERIFICATION_REPLAN_TIMEOUT",
                )

    async def _fail(
        self,
        record: ForgeSessionRecord,
        error: Exception,
        *,
        code: str | None = None,
    ) -> None:
        message = str(error) or type(error).__name__
        error_code = code or self._error_code(error)

        def mutate(current: ForgeSessionRecord) -> None:
            current.status = ForgeSessionStatus.FAILED
            current.error_code = error_code
            current.error_message = message
            if current.execution is None and current.dispatch_attempted_at is not None:
                current.execution = ExecutionRecord(
                    session_id=current.session_id,
                    command_id=current.command_id,
                    gateway_api_version=self.config.api_version,
                    action_type=current.request.action_type,
                    status="unknown",
                    timeline=ExecutionTimeline(terminal_observed_at=utc_now()),
                    error=ExecutionError(code=error_code, message=message),
                )

        record = self.store.update(
            record.session_id,
            mutate,
            event_type="session_failed",
            payload={"code": error_code, "message": message},
        )
        if self.verifier is not None:
            self.verifier.write_lesson(
                record,
                summary=message,
                phase="forge_orchestration",
                error_code=error_code,
            )
        await self._notify_terminal(record)

    async def _notify_terminal(self, record: ForgeSessionRecord) -> None:
        if self.bus is None or record.completion_notified_at is not None:
            return
        payload = {
            "session_id": record.session_id,
            "root_session_id": record.root_session_id,
            "status": record.status.value,
            "execution_status": record.execution.status if record.execution else None,
            "verification_verdict": (
                record.verification.verdict.verdict
                if record.verification.verdict is not None
                else None
            ),
            "error_code": record.error_code,
            "error_message": record.error_message,
        }
        await self.bus.publish_inbound(
            InboundMessage(
                channel="system",
                sender_id="forge-orchestrator",
                chat_id=f"{record.origin_channel}:{record.origin_chat_id}",
                session_key_override=record.origin_session_key,
                content=(
                    "[System: Forge task finished]\n"
                    "Report this task outcome to the user. Gateway execution success is only an "
                    "execution fact; use the supplied verification verdict for task success.\n\n"
                    + json.dumps(payload, ensure_ascii=False, indent=2)
                ),
                metadata={"forge_session_id": record.session_id},
            )
        )
        self.store.update(
            record.session_id,
            lambda current: setattr(current, "completion_notified_at", utc_now()),
            event_type="completion_notified",
        )

    @staticmethod
    def _abandon_verification(record: ForgeSessionRecord) -> None:
        record.status = ForgeSessionStatus.AWAITING_VERIFICATION
        record.verification.status = "pending"
        record.verification.attempts.append(
            VerificationAttempt(
                attempt_id=f"verification_{uuid4().hex[:12]}",
                error="verification interrupted by PAOS restart",
                abandoned=True,
            )
        )

    @staticmethod
    def _status_from_execution(record: ForgeSessionRecord) -> ForgeSessionStatus:
        status = record.execution.status if record.execution is not None else "unknown"
        return {
            "succeeded": ForgeSessionStatus.SUCCEEDED,
            "failed": ForgeSessionStatus.FAILED,
            "timed_out": ForgeSessionStatus.TIMED_OUT,
            "cancelled": ForgeSessionStatus.CANCELLED,
        }.get(status, ForgeSessionStatus.FAILED)

    @staticmethod
    def _execution_error_details(record: ForgeSessionRecord) -> tuple[str, str]:
        execution = record.execution
        if execution is None:
            return "FORGE_EXECUTION_FAILED", "Forge execution record is unavailable"
        error = execution.error
        code = error.code if error is not None and error.code else "FORGE_EXECUTION_FAILED"
        message = (
            error.message
            if error is not None and error.message
            else f"Gateway execution ended as {execution.status}"
        )
        return code, message

    @staticmethod
    def _error_code(error: Exception) -> str:
        message = str(error)
        if message.startswith("FORGE_") and ":" in message:
            return message.split(":", 1)[0]
        if isinstance(error, ForgeGatewayError):
            return "FORGE_GATEWAY_ERROR"
        return "FORGE_ORCHESTRATION_ERROR"

    @staticmethod
    def _verification_error_code(error: Exception) -> str:
        name = type(error).__name__
        if name == "VerificationEvidenceError":
            return "VERIFICATION_EVIDENCE_UNAVAILABLE"
        if name == "VerificationVerdictError":
            return "VERIFICATION_INVALID_VERDICT"
        if name == "VerificationBudgetError":
            return "VERIFICATION_CALL_BUDGET_EXHAUSTED"
        return "VERIFICATION_SERVICE_UNAVAILABLE"

    def _lessons(self) -> str:
        path = self.workspace / "LESSONS.md"
        return path.read_text(encoding="utf-8") if path.exists() else ""

    @staticmethod
    def _response_data(response: dict[str, Any]) -> dict[str, Any]:
        data = response.get("data")
        return dict(data) if isinstance(data, dict) else dict(response)

    def _require_enabled(self) -> None:
        if not self.config.enabled:
            raise RuntimeError("Forge execution is disabled")

    def _require_verifier(self, request: ForgeTaskRequest) -> None:
        if request.verification.mode != "off" and (
            self.verifier is None or self.verifier_error is not None
        ):
            raise RuntimeError(
                self.verifier_error or "non-off verification requires the verifier service"
            )
