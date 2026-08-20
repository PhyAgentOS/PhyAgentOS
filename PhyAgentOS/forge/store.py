"""Transactional SQLite store for Forge-only orchestration state."""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from PhyAgentOS.verification.contracts import (
    TERMINAL_FORGE_STATUSES,
    ForgeSessionRecord,
    ForgeSessionStatus,
    utc_now,
    validate_forge_transition,
)


class ForgeStoreError(RuntimeError):
    pass


class ForgeBusyError(ForgeStoreError):
    pass


class ForgeSessionStore:
    def __init__(self, workspace: str | Path) -> None:
        root = Path(workspace).expanduser().resolve() / ".paos" / "forge"
        root.mkdir(parents=True, exist_ok=True)
        self.path = root / "orchestrator.sqlite3"
        self._lock = threading.RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        return connection

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._lock, self._connection() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS forge_sessions (
                    session_id TEXT PRIMARY KEY,
                    command_id TEXT NOT NULL UNIQUE,
                    root_session_id TEXT NOT NULL,
                    parent_session_id TEXT UNIQUE,
                    status TEXT NOT NULL,
                    record_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS forge_sessions_root_idx
                    ON forge_sessions(root_session_id, created_at);
                CREATE INDEX IF NOT EXISTS forge_sessions_status_idx
                    ON forge_sessions(status);
                CREATE TABLE IF NOT EXISTS forge_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    FOREIGN KEY(session_id) REFERENCES forge_sessions(session_id)
                );
                """
            )

    def create(self, record: ForgeSessionRecord) -> ForgeSessionRecord:
        with self._lock, self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            active = connection.execute(
                "SELECT session_id FROM forge_sessions WHERE status NOT IN "
                f"({','.join('?' for _ in TERMINAL_FORGE_STATUSES)}) LIMIT 1",
                tuple(item.value for item in TERMINAL_FORGE_STATUSES),
            ).fetchone()
            if active is not None:
                raise ForgeBusyError(
                    f"Forge Gateway already has active PAOS session {active['session_id']}"
                )
            self._insert(connection, record)
            self._event(connection, record.session_id, "session_created", {})
            connection.commit()
        return record

    def create_replanned(
        self,
        parent_session_id: str,
        child: ForgeSessionRecord,
    ) -> tuple[ForgeSessionRecord, ForgeSessionRecord]:
        with self._lock, self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT record_json FROM forge_sessions WHERE parent_session_id = ?",
                (parent_session_id,),
            ).fetchone()
            if existing is not None:
                existing_child = ForgeSessionRecord.model_validate_json(existing["record_json"])
                parent = self._get(connection, parent_session_id)
                connection.rollback()
                return parent, existing_child
            parent = self._get(connection, parent_session_id)
            if parent.status != ForgeSessionStatus.AWAITING_REPLAN:
                raise ForgeStoreError(
                    f"parent session is not awaiting replan: {parent.status.value}"
                )
            validate_forge_transition(parent.status, ForgeSessionStatus.REPLANNED)
            parent.status = ForgeSessionStatus.REPLANNED
            parent.terminal_at = utc_now()
            parent.updated_at = utc_now()
            self._write(connection, parent)
            self._insert(connection, child)
            self._event(
                connection,
                parent.session_id,
                "session_replanned",
                {"child_session_id": child.session_id},
            )
            self._event(
                connection,
                child.session_id,
                "session_created",
                {"parent_session_id": parent.session_id},
            )
            connection.commit()
            return parent, child

    def get(self, session_id: str) -> ForgeSessionRecord:
        with self._lock, self._connection() as connection:
            return self._get(connection, session_id)

    def update(
        self,
        session_id: str,
        mutate: Callable[[ForgeSessionRecord], None],
        *,
        event_type: str = "session_updated",
        payload: dict[str, Any] | None = None,
    ) -> ForgeSessionRecord:
        with self._lock, self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            record = self._get(connection, session_id)
            previous = record.status
            mutate(record)
            validate_forge_transition(previous, record.status)
            record.updated_at = utc_now()
            if record.status in TERMINAL_FORGE_STATUSES and record.terminal_at is None:
                record.terminal_at = utc_now()
            self._write(connection, record)
            self._event(connection, session_id, event_type, payload or {})
            connection.commit()
            return record

    def transition(
        self,
        session_id: str,
        status: ForgeSessionStatus,
        *,
        event_type: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> ForgeSessionRecord:
        return self.update(
            session_id,
            lambda record: setattr(record, "status", status),
            event_type=event_type or f"status_{status.value}",
            payload=payload,
        )

    def nonterminal(self) -> list[ForgeSessionRecord]:
        placeholders = ",".join("?" for _ in TERMINAL_FORGE_STATUSES)
        with self._lock, self._connection() as connection:
            rows = connection.execute(
                f"SELECT record_json FROM forge_sessions WHERE status NOT IN ({placeholders}) "
                "ORDER BY created_at",
                tuple(item.value for item in TERMINAL_FORGE_STATUSES),
            ).fetchall()
        return [ForgeSessionRecord.model_validate_json(row["record_json"]) for row in rows]

    def lineage(self, root_session_id: str) -> list[ForgeSessionRecord]:
        with self._lock, self._connection() as connection:
            rows = connection.execute(
                "SELECT record_json FROM forge_sessions WHERE root_session_id = ? "
                "ORDER BY created_at",
                (root_session_id,),
            ).fetchall()
        return [ForgeSessionRecord.model_validate_json(row["record_json"]) for row in rows]

    def events(self, root_session_id: str, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock, self._connection() as connection:
            rows = connection.execute(
                "SELECT e.session_id, e.event_type, e.created_at, e.payload_json "
                "FROM forge_events e JOIN forge_sessions s ON s.session_id = e.session_id "
                "WHERE s.root_session_id = ? ORDER BY e.event_id DESC LIMIT ?",
                (root_session_id, max(1, int(limit))),
            ).fetchall()
        return [
            {
                "session_id": row["session_id"],
                "event_type": row["event_type"],
                "created_at": row["created_at"],
                "payload": json.loads(row["payload_json"]),
            }
            for row in reversed(rows)
        ]

    @staticmethod
    def _get(connection: sqlite3.Connection, session_id: str) -> ForgeSessionRecord:
        row = connection.execute(
            "SELECT record_json FROM forge_sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"Forge session not found: {session_id}")
        return ForgeSessionRecord.model_validate_json(row["record_json"])

    @staticmethod
    def _insert(connection: sqlite3.Connection, record: ForgeSessionRecord) -> None:
        try:
            connection.execute(
                "INSERT INTO forge_sessions "
                "(session_id, command_id, root_session_id, parent_session_id, status, "
                "record_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    record.session_id,
                    record.command_id,
                    record.root_session_id,
                    record.parent_session_id,
                    record.status.value,
                    record.model_dump_json(),
                    record.created_at.isoformat(),
                    record.updated_at.isoformat(),
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise ForgeStoreError(f"duplicate Forge session identity: {exc}") from exc

    @staticmethod
    def _write(connection: sqlite3.Connection, record: ForgeSessionRecord) -> None:
        connection.execute(
            "UPDATE forge_sessions SET status = ?, record_json = ?, updated_at = ? "
            "WHERE session_id = ?",
            (
                record.status.value,
                record.model_dump_json(),
                record.updated_at.isoformat(),
                record.session_id,
            ),
        )

    @staticmethod
    def _event(
        connection: sqlite3.Connection,
        session_id: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> None:
        connection.execute(
            "INSERT INTO forge_events (session_id, event_type, created_at, payload_json) "
            "VALUES (?, ?, ?, ?)",
            (
                session_id,
                event_type,
                utc_now().isoformat(),
                json.dumps(payload, ensure_ascii=False, sort_keys=True),
            ),
        )
