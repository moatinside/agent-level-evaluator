"""Read-only Outbox consumer with exact ledger-row read-back and separate ACK receipts.

This module is an isolated transport primitive. It does not choose a runtime root,
scan user data, run on a schedule, or mark an event eligible for capability scoring.
"""
from __future__ import annotations

import ctypes
import errno
import hashlib
import json
import os
import re
import sqlite3
import stat
import sys
import threading
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from scripts.runtime_evidence_contract import (
    MAX_ENVELOPE_BYTES,
    canonical_json,
    validate_event,
)

LEDGER_DB_VERSION = 1
LEDGER_RETENTION_DAYS = 60
MAX_PURGE_ROWS = 900
RECEIPT_SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schemas" / "runtime-evidence-transport-ack-v1.schema.json"
RECEIPT_SCHEMA = json.loads(RECEIPT_SCHEMA_PATH.read_text(encoding="utf-8"))
_RECEIPT_MAX_BYTES = 2048
_SINK_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_SHA256 = re.compile(r"^sha256:[a-f0-9]{64}$")
_HMAC_REF = re.compile(r"^hmac-sha256:v[1-9][0-9]*:[a-f0-9]{64}$")
_UTC_TIMESTAMP = re.compile(RECEIPT_SCHEMA["properties"]["acknowledged_at"]["pattern"])
_CONSUME_LOCK = threading.RLock()
_CANONICAL_TABLE_SQL = {
    "outbox_events": (
        "CREATE TABLE outbox_events (seq INTEGER PRIMARY KEY AUTOINCREMENT, "
        "event_ref TEXT NOT NULL UNIQUE, payload_hash TEXT NOT NULL, schema_version INTEGER NOT NULL, "
        "envelope_json BLOB NOT NULL, created_at TEXT NOT NULL)"
    ),
    "outbox_conflicts": (
        "CREATE TABLE outbox_conflicts (conflict_id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "event_ref TEXT NOT NULL, payload_hash TEXT NOT NULL, schema_version INTEGER NOT NULL, "
        "candidate_sha256 TEXT NOT NULL, envelope_json BLOB NOT NULL, recorded_at TEXT NOT NULL, "
        "UNIQUE(event_ref, candidate_sha256))"
    ),
    "runtime_events": (
        "CREATE TABLE runtime_events (event_ref TEXT NOT NULL PRIMARY KEY, payload_hash TEXT NOT NULL, "
        "schema_version INTEGER NOT NULL, envelope_json BLOB NOT NULL, record_hash TEXT NOT NULL, "
        "committed_at TEXT NOT NULL)"
    ),
    "runtime_event_conflicts": (
        "CREATE TABLE runtime_event_conflicts (conflict_id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "event_ref TEXT NOT NULL, payload_hash TEXT NOT NULL, schema_version INTEGER NOT NULL, "
        "candidate_sha256 TEXT NOT NULL, envelope_json BLOB NOT NULL, recorded_at TEXT NOT NULL, "
        "UNIQUE(event_ref, candidate_sha256))"
    ),
    "transport_receipts": (
        "CREATE TABLE transport_receipts (event_ref TEXT NOT NULL, payload_hash TEXT NOT NULL, "
        "schema_version INTEGER NOT NULL, sink_id TEXT NOT NULL, receipt_json BLOB NOT NULL, "
        "PRIMARY KEY(event_ref, payload_hash, schema_version, sink_id))"
    ),
}


class ConsumerError(RuntimeError):
    """Value-free consumer failure code, optionally with stable validator codes."""

    def __init__(self, code: str, error_codes: tuple[str, ...] = ()):
        self.code = code
        self.error_codes = error_codes
        super().__init__(code)


@dataclass(frozen=True)
class ConsumerResult:
    status: str
    event_ref: str
    payload_hash: str
    receipt: dict[str, Any] | None = None


@dataclass(frozen=True)
class LedgerPurgeResult:
    cutoff: str
    events_deleted: int
    conflicts_deleted: int
    receipts_deleted: int
    has_more: bool


def _safe_timestamp(clock: Callable[[], datetime]) -> str:
    try:
        value = clock()
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise ValueError
        if value.utcoffset() != timezone.utc.utcoffset(value):
            raise ValueError
        return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
    except (TypeError, ValueError, OverflowError):
        raise ConsumerError("clock_invalid") from None


def _parse_canonical_timestamp(value: Any) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ConsumerError("ledger_timestamp_invalid")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        raise ConsumerError("ledger_timestamp_invalid") from None
    if _safe_timestamp(lambda: parsed) != value:
        raise ConsumerError("ledger_timestamp_invalid")
    return parsed


_DARWIN_ACL_API: Any | None = None
if sys.platform == "darwin":
    try:
        _DARWIN_ACL_API = ctypes.CDLL("/usr/lib/libSystem.B.dylib", use_errno=True)
        _DARWIN_ACL_API.acl_get_file.argtypes = (ctypes.c_char_p, ctypes.c_int)
        _DARWIN_ACL_API.acl_get_file.restype = ctypes.c_void_p
        _DARWIN_ACL_API.acl_free.argtypes = (ctypes.c_void_p,)
        _DARWIN_ACL_API.acl_free.restype = ctypes.c_int
        _DARWIN_ACL_API.acl_get_entry.argtypes = (
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_void_p),
        )
        _DARWIN_ACL_API.acl_get_entry.restype = ctypes.c_int
        _DARWIN_ACL_API.acl_get_tag_type.argtypes = (ctypes.c_void_p, ctypes.POINTER(ctypes.c_int))
        _DARWIN_ACL_API.acl_get_tag_type.restype = ctypes.c_int
    except (AttributeError, OSError):
        _DARWIN_ACL_API = None

_ACL_FIRST_ENTRY = 0
_ACL_NEXT_ENTRY = -1
_ACL_EXTENDED_DENY = 2


def _has_extended_acl(path: Path) -> bool:
    if sys.platform == "darwin":
        api = _DARWIN_ACL_API
        if api is None:
            raise OSError(errno.ENOTSUP, "ACL query unavailable")
        ctypes.set_errno(0)
        acl = api.acl_get_file(os.fsencode(path), 0x100)  # ACL_TYPE_EXTENDED
        error = ctypes.get_errno()
        if acl:
            if api.acl_free(acl) != 0:
                raise OSError(ctypes.get_errno() or errno.EIO, "ACL release failed")
            return True
        if error == errno.ENOENT:
            return False
        raise OSError(error or errno.EIO, "ACL query failed")
    if sys.platform.startswith("linux"):
        names = os.listxattr(path, follow_symlinks=False)
        return "system.posix_acl_access" in names or "system.posix_acl_default" in names
    raise OSError(errno.ENOTSUP, "ACL query unavailable")


def _has_non_deny_acl(path: Path) -> bool:
    """Parent-directory ACL policy.

    Deny-only entries cannot grant access (macOS puts ``group:everyone deny
    delete`` on every home directory), so they are accepted on parents. Any
    allow or unknown entry, or any ACL API failure, fails closed. DB inodes
    still use the stricter ``_has_extended_acl`` (no ACL at all).
    """
    if sys.platform != "darwin":
        return _has_extended_acl(path)
    api = _DARWIN_ACL_API
    if api is None:
        raise OSError(errno.ENOTSUP, "ACL query unavailable")
    ctypes.set_errno(0)
    acl = api.acl_get_file(os.fsencode(path), 0x100)  # ACL_TYPE_EXTENDED
    error = ctypes.get_errno()
    if not acl:
        if error == errno.ENOENT:
            return False
        raise OSError(error or errno.EIO, "ACL query failed")
    try:
        entry = ctypes.c_void_p()
        tag = ctypes.c_int()
        entry_id = _ACL_FIRST_ENTRY
        while True:
            ctypes.set_errno(0)
            if api.acl_get_entry(acl, entry_id, ctypes.byref(entry)) != 0:
                if ctypes.get_errno() == errno.EINVAL:
                    return False
                raise OSError(ctypes.get_errno() or errno.EIO, "ACL entry query failed")
            if api.acl_get_tag_type(entry, ctypes.byref(tag)) != 0:
                raise OSError(ctypes.get_errno() or errno.EIO, "ACL tag query failed")
            if tag.value != _ACL_EXTENDED_DENY:
                return True
            entry_id = _ACL_NEXT_ENTRY
    finally:
        if api.acl_free(acl) != 0:
            raise OSError(ctypes.get_errno() or errno.EIO, "ACL release failed")


def _validate_parent_chain(path: Path) -> None:
    if not path.is_absolute() or ".." in path.parts:
        raise ConsumerError("database_path_invalid")
    effective_uid = os.geteuid() if os.name == "posix" else None
    pending = [path]
    checked: set[Path] = set()
    while pending:
        current = pending.pop()
        if current in checked:
            continue
        checked.add(current)
        try:
            info = current.lstat()
        except OSError:
            raise ConsumerError("database_path_invalid") from None
        if stat.S_ISLNK(info.st_mode):
            if effective_uid is None or info.st_uid != 0:
                raise ConsumerError("database_path_invalid")
            try:
                resolved = current.resolve(strict=True)
            except OSError:
                raise ConsumerError("database_path_invalid") from None
            pending.append(resolved)
            if current.parent != current:
                pending.append(current.parent)
            continue
        if not stat.S_ISDIR(info.st_mode):
            raise ConsumerError("database_path_invalid")
        try:
            if _has_non_deny_acl(current):
                raise ConsumerError("database_permissions_invalid")
        except OSError:
            raise ConsumerError("database_permissions_invalid") from None
        if effective_uid is not None:
            if info.st_uid not in (0, effective_uid):
                raise ConsumerError("database_permissions_invalid")
            writable_by_others = info.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
            sticky = info.st_mode & stat.S_ISVTX
            if writable_by_others and not sticky:
                raise ConsumerError("database_permissions_invalid")
        if current.parent != current:
            pending.append(current.parent)


def _ensure_private_regular_file(path: Path, *, create: bool) -> None:
    if not path.is_absolute():
        raise ConsumerError("database_path_invalid")
    _validate_parent_chain(path.parent)
    try:
        try:
            info = path.lstat()
        except FileNotFoundError:
            if not create:
                raise ConsumerError("database_unavailable")
            flags = os.O_CREAT | os.O_EXCL | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
            try:
                fd = os.open(path, flags, 0o600)
            except FileExistsError:
                pass
            else:
                os.close(fd)
            info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
            raise ConsumerError("database_path_invalid")
        try:
            if _has_extended_acl(path):
                raise ConsumerError("database_permissions_invalid")
        except OSError:
            raise ConsumerError("database_permissions_invalid") from None
        if os.name == "posix" and (
            info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & 0o077
        ):
            raise ConsumerError("database_permissions_invalid")
    except ConsumerError:
        raise
    except OSError:
        raise ConsumerError("database_unavailable") from None


def _connect_writer(path: Path, *, create: bool) -> sqlite3.Connection:
    _ensure_private_regular_file(path, create=create)
    try:
        conn = sqlite3.connect(str(path), timeout=5, isolation_level=None)
        conn.execute("PRAGMA busy_timeout=5000")
        journal_mode = str(conn.execute("PRAGMA journal_mode").fetchone()[0]).lower()
        if journal_mode != "delete":
            conn.close()
            raise ConsumerError("database_journal_mode_unsupported")
        conn.execute("PRAGMA synchronous=FULL")
        return conn
    except sqlite3.Error:
        raise ConsumerError("ledger_unavailable") from None


def _connect_readonly(path: Path) -> sqlite3.Connection:
    _ensure_private_regular_file(path, create=False)
    try:
        conn = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=5)
        conn.execute("PRAGMA query_only=ON")
        journal_mode = str(conn.execute("PRAGMA journal_mode").fetchone()[0]).lower()
        if journal_mode != "delete":
            conn.close()
            raise ConsumerError("database_journal_mode_unsupported")
        return conn
    except sqlite3.Error:
        raise ConsumerError("database_unavailable") from None


def _validate_table(
    conn: sqlite3.Connection,
    table: str,
    expected: dict[str, tuple[str, int, int]],
    error_code: str,
) -> None:
    rows = conn.execute(f'PRAGMA table_info("{table}")').fetchall()
    actual = {row[1]: (str(row[2]).upper(), int(row[3]), int(row[5])) for row in rows}
    if actual != expected:
        raise ConsumerError(error_code)


def _has_unique_columns(conn: sqlite3.Connection, table: str, expected: tuple[str, ...]) -> bool:
    try:
        indexes = conn.execute(
            'SELECT name FROM pragma_index_list(?) WHERE "unique"=1 AND partial=0', (table,)
        ).fetchall()
        for (name,) in indexes:
            columns = tuple(
                row[0] for row in conn.execute(
                    "SELECT name FROM pragma_index_info(?) ORDER BY seqno", (name,)
                ).fetchall()
            )
            if columns == expected:
                return True
        return False
    except sqlite3.Error:
        return False


def _assert_objects(conn: sqlite3.Connection, expected_tables: set[str], error_code: str) -> None:
    tables = {
        row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT GLOB 'sqlite_*'"
        ).fetchall()
    }
    triggers_or_views = conn.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type IN ('trigger', 'view')"
    ).fetchone()[0]
    custom_indexes = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='index' AND sql IS NOT NULL LIMIT 1"
    ).fetchone()
    if tables != expected_tables or triggers_or_views or custom_indexes is not None:
        raise ConsumerError(error_code)


def _assert_canonical_table_ddl(
    conn: sqlite3.Connection,
    expected_tables: set[str],
    error_code: str,
) -> None:
    for table in expected_tables:
        row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()
        expected = _CANONICAL_TABLE_SQL[table]
        if row is None or not isinstance(row[0], str):
            raise ConsumerError(error_code)
        if " ".join(row[0].split()).casefold() != " ".join(expected.split()).casefold():
            raise ConsumerError(error_code)


def _validate_outbox_schema(conn: sqlite3.Connection) -> None:
    error_code = "outbox_schema_unsupported"
    expected_tables = {"outbox_events", "outbox_conflicts"}
    _assert_objects(conn, expected_tables, error_code)
    _assert_canonical_table_ddl(conn, expected_tables, error_code)
    _validate_table(conn, "outbox_events", {
        "seq": ("INTEGER", 0, 1),
        "event_ref": ("TEXT", 1, 0),
        "payload_hash": ("TEXT", 1, 0),
        "schema_version": ("INTEGER", 1, 0),
        "envelope_json": ("BLOB", 1, 0),
        "created_at": ("TEXT", 1, 0),
    }, error_code)
    _validate_table(conn, "outbox_conflicts", {
        "conflict_id": ("INTEGER", 0, 1),
        "event_ref": ("TEXT", 1, 0),
        "payload_hash": ("TEXT", 1, 0),
        "schema_version": ("INTEGER", 1, 0),
        "candidate_sha256": ("TEXT", 1, 0),
        "envelope_json": ("BLOB", 1, 0),
        "recorded_at": ("TEXT", 1, 0),
    }, error_code)
    if not _has_unique_columns(conn, "outbox_events", ("event_ref",)):
        raise ConsumerError(error_code)
    if not _has_unique_columns(conn, "outbox_conflicts", ("event_ref", "candidate_sha256")):
        raise ConsumerError(error_code)


def _validate_ledger_schema(conn: sqlite3.Connection) -> None:
    error_code = "ledger_schema_unsupported"
    expected_tables = {"runtime_events", "runtime_event_conflicts", "transport_receipts"}
    _assert_objects(conn, expected_tables, error_code)
    _assert_canonical_table_ddl(conn, expected_tables, error_code)
    _validate_table(conn, "runtime_events", {
        "event_ref": ("TEXT", 1, 1),
        "payload_hash": ("TEXT", 1, 0),
        "schema_version": ("INTEGER", 1, 0),
        "envelope_json": ("BLOB", 1, 0),
        "record_hash": ("TEXT", 1, 0),
        "committed_at": ("TEXT", 1, 0),
    }, error_code)
    _validate_table(conn, "runtime_event_conflicts", {
        "conflict_id": ("INTEGER", 0, 1),
        "event_ref": ("TEXT", 1, 0),
        "payload_hash": ("TEXT", 1, 0),
        "schema_version": ("INTEGER", 1, 0),
        "candidate_sha256": ("TEXT", 1, 0),
        "envelope_json": ("BLOB", 1, 0),
        "recorded_at": ("TEXT", 1, 0),
    }, error_code)
    _validate_table(conn, "transport_receipts", {
        "event_ref": ("TEXT", 1, 1),
        "payload_hash": ("TEXT", 1, 2),
        "schema_version": ("INTEGER", 1, 3),
        "sink_id": ("TEXT", 1, 4),
        "receipt_json": ("BLOB", 1, 0),
    }, error_code)
    if not _has_unique_columns(conn, "runtime_event_conflicts", ("event_ref", "candidate_sha256")):
        raise ConsumerError(error_code)


def _has_non_internal_schema_objects(conn: sqlite3.Connection) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master "
        "WHERE type IN ('table', 'view', 'trigger', 'index') "
        "AND name NOT GLOB 'sqlite_*' LIMIT 1"
    ).fetchone() is not None


def _ensure_ledger_schema(conn: sqlite3.Connection, *, allow_initialize: bool) -> None:
    try:
        version = int(conn.execute("PRAGMA user_version").fetchone()[0])
        if version == LEDGER_DB_VERSION:
            _validate_ledger_schema(conn)
            return
        if version != 0 or not allow_initialize:
            raise ConsumerError("ledger_schema_unsupported")
        if _has_non_internal_schema_objects(conn):
            raise ConsumerError("ledger_schema_unsupported")
        conn.execute("BEGIN IMMEDIATE")
        locked_version = int(conn.execute("PRAGMA user_version").fetchone()[0])
        if locked_version == LEDGER_DB_VERSION:
            conn.commit()
            _validate_ledger_schema(conn)
            return
        if locked_version != 0:
            raise ConsumerError("ledger_schema_unsupported")
        if _has_non_internal_schema_objects(conn):
            raise ConsumerError("ledger_schema_unsupported")
        conn.execute(
            "CREATE TABLE runtime_events ("
            "event_ref TEXT NOT NULL PRIMARY KEY, payload_hash TEXT NOT NULL, schema_version INTEGER NOT NULL, "
            "envelope_json BLOB NOT NULL, record_hash TEXT NOT NULL, committed_at TEXT NOT NULL)"
        )
        conn.execute(
            "CREATE TABLE runtime_event_conflicts ("
            "conflict_id INTEGER PRIMARY KEY AUTOINCREMENT, event_ref TEXT NOT NULL, "
            "payload_hash TEXT NOT NULL, schema_version INTEGER NOT NULL, candidate_sha256 TEXT NOT NULL, "
            "envelope_json BLOB NOT NULL, recorded_at TEXT NOT NULL, UNIQUE(event_ref, candidate_sha256))"
        )
        conn.execute(
            "CREATE TABLE transport_receipts ("
            "event_ref TEXT NOT NULL, payload_hash TEXT NOT NULL, schema_version INTEGER NOT NULL, "
            "sink_id TEXT NOT NULL, receipt_json BLOB NOT NULL, "
            "PRIMARY KEY(event_ref, payload_hash, schema_version, sink_id))"
        )
        conn.execute(f"PRAGMA user_version={LEDGER_DB_VERSION}")
        conn.commit()
        _validate_ledger_schema(conn)
    except ConsumerError:
        if conn.in_transaction:
            conn.rollback()
        raise
    except sqlite3.Error:
        if conn.in_transaction:
            conn.rollback()
        raise ConsumerError("ledger_unavailable") from None


def initialize_runtime_evidence_ledger(database_path: str | os.PathLike[str]) -> None:
    """Initialize the ledger at an explicitly chosen path; never called by the consumer."""
    path = Path(database_path)
    conn = _connect_writer(path, create=True)
    try:
        _ensure_ledger_schema(conn, allow_initialize=True)
    finally:
        conn.close()


def purge_expired_runtime_evidence_ledger(
    database_path: str | os.PathLike[str],
    *,
    now: datetime,
    max_rows: int = MAX_PURGE_ROWS,
) -> LedgerPurgeResult:
    """Manually purge up to ``max_rows`` ledger rows beyond the approved 60-day window.

    Expired event receipts are removed before their parent event. This function is
    not called by the consumer or any scheduler; invalid timestamps and orphaned
    receipts fail closed.
    """
    if type(max_rows) is not int or not 1 <= max_rows <= MAX_PURGE_ROWS:
        raise ConsumerError("ledger_purge_limit_invalid")
    now_text = _safe_timestamp(lambda: now)
    now_value = _parse_canonical_timestamp(now_text)
    try:
        cutoff_value = now_value - timedelta(days=LEDGER_RETENTION_DAYS)
    except OverflowError:
        raise ConsumerError("clock_invalid") from None
    cutoff = _safe_timestamp(lambda: cutoff_value)

    path = Path(database_path)
    conn = _connect_writer(path, create=False)
    deleted_events: list[str] = []
    deleted_conflicts: list[int] = []
    deleted_receipts: list[tuple[str, str, int, str]] = []
    remaining = max_rows
    try:
        conn.execute("BEGIN IMMEDIATE")
        _ensure_ledger_schema(conn, allow_initialize=False)
        orphan = conn.execute(
            "SELECT r.event_ref FROM transport_receipts r "
            "LEFT JOIN runtime_events e ON e.event_ref=r.event_ref "
            "WHERE e.event_ref IS NULL OR r.payload_hash<>e.payload_hash "
            "OR r.schema_version<>e.schema_version LIMIT 1"
        ).fetchone()
        if orphan is not None:
            raise ConsumerError("ledger_receipt_orphaned")

        expired_events = conn.execute(
            "SELECT event_ref, committed_at FROM runtime_events "
            "WHERE committed_at < ? ORDER BY committed_at, event_ref LIMIT ?",
            (cutoff, remaining),
        ).fetchall()
        for event_ref, committed_at in expired_events:
            if _parse_canonical_timestamp(committed_at) >= cutoff_value:
                raise ConsumerError("ledger_timestamp_invalid")
            if remaining == 0:
                break
            receipt_rows = conn.execute(
                "SELECT payload_hash, schema_version, sink_id FROM transport_receipts "
                "WHERE event_ref=? ORDER BY payload_hash, schema_version, sink_id LIMIT ?",
                (event_ref, remaining),
            ).fetchall()
            for payload_hash, schema_version, sink_id in receipt_rows:
                cursor = conn.execute(
                    "DELETE FROM transport_receipts WHERE event_ref=? AND payload_hash=? "
                    "AND schema_version=? AND sink_id=?",
                    (event_ref, payload_hash, schema_version, sink_id),
                )
                if cursor.rowcount != 1:
                    raise ConsumerError("ledger_purge_unconfirmed")
                deleted_receipts.append(
                    (event_ref, payload_hash, schema_version, sink_id)
                )
                remaining -= 1

            receipt_remains = conn.execute(
                "SELECT 1 FROM transport_receipts WHERE event_ref=? LIMIT 1",
                (event_ref,),
            ).fetchone()
            if receipt_remains is not None or remaining == 0:
                continue
            cursor = conn.execute(
                "DELETE FROM runtime_events WHERE event_ref=? AND committed_at < ?",
                (event_ref, cutoff),
            )
            if cursor.rowcount != 1:
                raise ConsumerError("ledger_purge_unconfirmed")
            deleted_events.append(event_ref)
            remaining -= 1

        if remaining > 0:
            conflict_rows = conn.execute(
                "SELECT conflict_id, recorded_at FROM runtime_event_conflicts "
                "WHERE recorded_at < ? ORDER BY conflict_id LIMIT ?",
                (cutoff, remaining),
            ).fetchall()
            ids: list[int] = []
            for conflict_id, recorded_at in conflict_rows:
                if _parse_canonical_timestamp(recorded_at) >= cutoff_value:
                    raise ConsumerError("ledger_timestamp_invalid")
                ids.append(int(conflict_id))
            if ids:
                placeholders = ",".join("?" for _ in ids)
                cursor = conn.execute(
                    f"DELETE FROM runtime_event_conflicts WHERE conflict_id IN ({placeholders}) "
                    "AND recorded_at < ?",
                    (*ids, cutoff),
                )
                if cursor.rowcount != len(ids):
                    raise ConsumerError("ledger_purge_unconfirmed")
                deleted_conflicts.extend(ids)
                remaining -= len(ids)
        conn.commit()
    except ConsumerError:
        if conn.in_transaction:
            conn.rollback()
        raise
    except sqlite3.Error:
        if conn.in_transaction:
            conn.rollback()
        raise ConsumerError("ledger_unavailable") from None
    finally:
        conn.close()

    has_more = False
    try:
        with closing(_connect_readonly(path)) as read_conn:
            _ensure_ledger_schema(read_conn, allow_initialize=False)
            orphan = read_conn.execute(
                "SELECT r.event_ref FROM transport_receipts r "
                "LEFT JOIN runtime_events e ON e.event_ref=r.event_ref "
                "WHERE e.event_ref IS NULL OR r.payload_hash<>e.payload_hash "
                "OR r.schema_version<>e.schema_version LIMIT 1"
            ).fetchone()
            if orphan is not None:
                raise ConsumerError("ledger_receipt_orphaned")
            if deleted_events:
                placeholders = ",".join("?" for _ in deleted_events)
                if read_conn.execute(
                    f"SELECT 1 FROM runtime_events WHERE event_ref IN ({placeholders}) LIMIT 1",
                    deleted_events,
                ).fetchone():
                    raise ConsumerError("ledger_purge_readback_mismatch")
            if deleted_conflicts:
                placeholders = ",".join("?" for _ in deleted_conflicts)
                if read_conn.execute(
                    f"SELECT 1 FROM runtime_event_conflicts "
                    f"WHERE conflict_id IN ({placeholders}) LIMIT 1",
                    deleted_conflicts,
                ).fetchone():
                    raise ConsumerError("ledger_purge_readback_mismatch")
            for event_ref, payload_hash, schema_version, sink_id in deleted_receipts:
                if read_conn.execute(
                    "SELECT 1 FROM transport_receipts WHERE event_ref=? AND payload_hash=? "
                    "AND schema_version=? AND sink_id=? LIMIT 1",
                    (event_ref, payload_hash, schema_version, sink_id),
                ).fetchone():
                    raise ConsumerError("ledger_purge_readback_mismatch")
            for table, timestamp_column, order_column in (
                ("runtime_events", "committed_at", "event_ref"),
                ("runtime_event_conflicts", "recorded_at", "conflict_id"),
            ):
                candidate = read_conn.execute(
                    f"SELECT {timestamp_column} FROM {table} WHERE {timestamp_column} < ? "
                    f"ORDER BY {timestamp_column}, {order_column} LIMIT 1",
                    (cutoff,),
                ).fetchone()
                if candidate is not None:
                    if _parse_canonical_timestamp(candidate[0]) >= cutoff_value:
                        raise ConsumerError("ledger_timestamp_invalid")
                    has_more = True
    except ConsumerError:
        raise
    except (OSError, sqlite3.Error, TypeError, ValueError):
        raise ConsumerError("ledger_purge_readback_unavailable") from None

    return LedgerPurgeResult(
        cutoff=cutoff,
        events_deleted=len(deleted_events),
        conflicts_deleted=len(deleted_conflicts),
        receipts_deleted=len(deleted_receipts),
        has_more=has_more,
    )


def _validate_receipt(receipt: Any) -> bool:
    if not isinstance(receipt, dict) or set(receipt) != set(RECEIPT_SCHEMA["required"]):
        return False
    for key, schema in RECEIPT_SCHEMA["properties"].items():
        value = receipt.get(key)
        if "const" in schema:
            expected = schema["const"]
            if isinstance(expected, int) and type(value) is not int:
                return False
            if value != expected:
                return False
        if "enum" in schema and value not in schema["enum"]:
            return False
        if schema.get("type") == "string":
            if not isinstance(value, str) or len(value) > schema.get("maxLength", len(value)):
                return False
            pattern = schema.get("pattern")
            if pattern and re.fullmatch(pattern, value) is None:
                return False
            if schema.get("format") == "date-time":
                try:
                    parsed = datetime.fromisoformat(value[:-1] + "+00:00")
                except ValueError:
                    return False
                if parsed.utcoffset() != timezone.utc.utcoffset(parsed):
                    return False
    try:
        return len(canonical_json(receipt)) <= _RECEIPT_MAX_BYTES
    except (TypeError, ValueError, OverflowError, RecursionError, UnicodeError):
        return False


def _decode_envelope(envelope_json: bytes) -> tuple[dict[str, Any], bytes]:
    if not isinstance(envelope_json, bytes) or len(envelope_json) > MAX_ENVELOPE_BYTES:
        raise ConsumerError("event_too_large")
    try:
        event = json.loads(envelope_json.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError, RecursionError):
        raise ConsumerError("event_invalid_json") from None
    try:
        error_codes = validate_event(event)
    except Exception:
        raise ConsumerError("contract_validator_failed") from None
    if error_codes:
        raise ConsumerError("event_rejected", tuple(error_codes))
    try:
        canonical = canonical_json(event)
    except (TypeError, ValueError, OverflowError, RecursionError, UnicodeError):
        raise ConsumerError("event_invalid_json") from None
    if canonical != envelope_json:
        raise ConsumerError("event_noncanonical")
    if not isinstance(event, dict):
        raise ConsumerError("event_rejected")
    event_ref = event.get("event_ref")
    payload_hash = event.get("payload_hash")
    if (
        not isinstance(event_ref, str)
        or _HMAC_REF.fullmatch(event_ref) is None
        or not isinstance(payload_hash, str)
        or _SHA256.fullmatch(payload_hash) is None
        or type(event.get("schema_version")) is not int
        or event.get("schema_version") != 2
    ):
        raise ConsumerError("event_rejected")
    return event, canonical


def _read_outbox_row(outbox_path: Path, seq: int) -> tuple[str, str, int, bytes]:
    if type(seq) is not int or seq < 1:
        raise ConsumerError("outbox_sequence_invalid")
    with closing(_connect_readonly(outbox_path)) as conn:
        try:
            version = int(conn.execute("PRAGMA user_version").fetchone()[0])
            if version != 1:
                raise ConsumerError("outbox_schema_unsupported")
            _validate_outbox_schema(conn)
            row = conn.execute(
                "SELECT event_ref, payload_hash, schema_version, envelope_json "
                "FROM outbox_events WHERE seq=?",
                (seq,),
            ).fetchone()
        except ConsumerError:
            raise
        except sqlite3.Error:
            raise ConsumerError("outbox_unavailable") from None
    if row is None:
        raise ConsumerError("outbox_event_not_found")
    event_ref, payload_hash, schema_version, envelope_json = row
    if not isinstance(event_ref, str) or not isinstance(payload_hash, str) or type(schema_version) is not int:
        raise ConsumerError("outbox_record_invalid")
    if not isinstance(envelope_json, bytes):
        raise ConsumerError("outbox_record_invalid")
    return event_ref, payload_hash, schema_version, envelope_json


def _read_ledger_event(path: Path, event_ref: str) -> tuple[str, str, int, bytes, str] | None:
    with closing(_connect_readonly(path)) as conn:
        try:
            version = int(conn.execute("PRAGMA user_version").fetchone()[0])
            if version != LEDGER_DB_VERSION:
                raise ConsumerError("ledger_schema_unsupported")
            _validate_ledger_schema(conn)
            row = conn.execute(
                "SELECT event_ref, payload_hash, schema_version, envelope_json, record_hash "
                "FROM runtime_events WHERE event_ref=?",
                (event_ref,),
            ).fetchone()
        except ConsumerError:
            raise
        except sqlite3.Error:
            raise ConsumerError("ledger_readback_unavailable") from None
    if row is None:
        return None
    return row[0], row[1], int(row[2]), bytes(row[3]), row[4]


def _read_receipt(path: Path, event_ref: str, payload_hash: str, sink_id: str) -> bytes | None:
    with closing(_connect_readonly(path)) as conn:
        try:
            version = int(conn.execute("PRAGMA user_version").fetchone()[0])
            if version != LEDGER_DB_VERSION:
                raise ConsumerError("ledger_schema_unsupported")
            _validate_ledger_schema(conn)
            row = conn.execute(
                "SELECT receipt_json FROM transport_receipts "
                "WHERE event_ref=? AND payload_hash=? AND schema_version=2 AND sink_id=?",
                (event_ref, payload_hash, sink_id),
            ).fetchone()
        except sqlite3.Error:
            raise ConsumerError("receipt_readback_unavailable") from None
    return None if row is None else bytes(row[0])


class RuntimeEvidenceConsumer:
    """Consume one Outbox row and ACK only after exact event and receipt read-back."""

    def __init__(
        self,
        ledger_db_path: str | os.PathLike[str],
        *,
        sink_id: str,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not isinstance(sink_id, str) or _SINK_ID.fullmatch(sink_id) is None:
            raise ConsumerError("sink_id_invalid")
        self.ledger_db_path = Path(ledger_db_path)
        self.sink_id = sink_id
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def consume_outbox_event(
        self,
        outbox_db_path: str | os.PathLike[str],
        *,
        seq: int,
    ) -> ConsumerResult:
        with _CONSUME_LOCK:
            return self._consume_outbox_event_locked(outbox_db_path, seq=seq)

    def _consume_outbox_event_locked(
        self,
        outbox_db_path: str | os.PathLike[str],
        *,
        seq: int,
    ) -> ConsumerResult:
        outbox_path = Path(outbox_db_path)
        if not outbox_path.is_absolute() or not self.ledger_db_path.is_absolute():
            raise ConsumerError("database_path_invalid")
        if os.path.abspath(outbox_path) == os.path.abspath(self.ledger_db_path):
            raise ConsumerError("database_paths_must_differ")
        event_ref_column, payload_hash_column, schema_version_column, envelope_json = _read_outbox_row(outbox_path, seq)
        event, canonical = _decode_envelope(envelope_json)
        if (
            event.get("event_ref") != event_ref_column
            or event.get("payload_hash") != payload_hash_column
            or event.get("schema_version") != schema_version_column
        ):
            raise ConsumerError("outbox_envelope_mismatch")
        return self._persist_and_ack(event, canonical)

    def _persist_and_ack(self, event: dict[str, Any], canonical: bytes) -> ConsumerResult:
        event_ref = event["event_ref"]
        payload_hash = event["payload_hash"]
        schema_version = event["schema_version"]
        record_hash = "sha256:" + hashlib.sha256(canonical).hexdigest()
        candidate_sha256 = hashlib.sha256(canonical).hexdigest()
        committed_at = _safe_timestamp(self.clock)
        conn = _connect_writer(self.ledger_db_path, create=False)
        disposition: str
        try:
            _ensure_ledger_schema(conn, allow_initialize=False)
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT payload_hash, schema_version, envelope_json, record_hash "
                "FROM runtime_events WHERE event_ref=?",
                (event_ref,),
            ).fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO runtime_events "
                    "(event_ref, payload_hash, schema_version, envelope_json, record_hash, committed_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (event_ref, payload_hash, schema_version, canonical, record_hash, committed_at),
                )
                disposition = "persisted"
            elif (
                row[0] == payload_hash
                and row[1] == schema_version
                and bytes(row[2]) == canonical
                and row[3] == record_hash
            ):
                disposition = "duplicate"
            else:
                conn.execute(
                    "INSERT OR IGNORE INTO runtime_event_conflicts "
                    "(event_ref, payload_hash, schema_version, candidate_sha256, envelope_json, recorded_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (event_ref, payload_hash, schema_version, candidate_sha256, canonical, committed_at),
                )
                disposition = "conflict"
            conn.commit()
        except ConsumerError:
            if conn.in_transaction:
                conn.rollback()
            raise
        except sqlite3.Error:
            if conn.in_transaction:
                conn.rollback()
            raise ConsumerError("ledger_write_unavailable") from None
        finally:
            conn.close()

        if disposition == "conflict":
            with closing(_connect_readonly(self.ledger_db_path)) as read_conn:
                try:
                    row = read_conn.execute(
                        "SELECT event_ref, payload_hash, schema_version, candidate_sha256, envelope_json "
                        "FROM runtime_event_conflicts WHERE event_ref=? AND candidate_sha256=?",
                        (event_ref, candidate_sha256),
                    ).fetchone()
                except sqlite3.Error:
                    raise ConsumerError("conflict_readback_unavailable") from None
            if row is None or tuple(row[:4]) != (
                event_ref, payload_hash, schema_version, candidate_sha256
            ) or bytes(row[4]) != canonical:
                raise ConsumerError("conflict_readback_mismatch")
            return ConsumerResult("conflict", event_ref, payload_hash)

        stored = _read_ledger_event(self.ledger_db_path, event_ref)
        if stored != (event_ref, payload_hash, schema_version, canonical, record_hash):
            raise ConsumerError("ledger_readback_mismatch")

        existing_receipt = _read_receipt(self.ledger_db_path, event_ref, payload_hash, self.sink_id)
        if existing_receipt is not None:
            try:
                receipt = json.loads(existing_receipt.decode("utf-8"))
            except (UnicodeError, json.JSONDecodeError, RecursionError):
                raise ConsumerError("receipt_invalid") from None
            if (
                not _validate_receipt(receipt)
                or receipt.get("event_ref") != event_ref
                or receipt.get("payload_hash") != payload_hash
                or receipt.get("event_schema_version") != schema_version
                or receipt.get("sink_id") != self.sink_id
                or receipt.get("ledger_record_hash") != record_hash
                or canonical_json(receipt) != existing_receipt
            ):
                raise ConsumerError("receipt_readback_mismatch")
            return ConsumerResult("acknowledged", event_ref, payload_hash, receipt)

        receipt = {
            "receipt_type": "runtime_evidence_transport_ack",
            "receipt_schema_version": 1,
            "sink_id": self.sink_id,
            "event_ref": event_ref,
            "payload_hash": payload_hash,
            "event_schema_version": schema_version,
            "disposition": disposition,
            "ledger_record_hash": record_hash,
            "readback_status": "exact_match",
            "acknowledged_at": _safe_timestamp(self.clock),
        }
        if not _validate_receipt(receipt):
            raise ConsumerError("receipt_invalid")
        receipt_json = canonical_json(receipt)
        conn = _connect_writer(self.ledger_db_path, create=False)
        try:
            _ensure_ledger_schema(conn, allow_initialize=False)
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                "SELECT receipt_json FROM transport_receipts "
                "WHERE event_ref=? AND payload_hash=? AND schema_version=? AND sink_id=?",
                (event_ref, payload_hash, schema_version, self.sink_id),
            ).fetchone()
            if existing is None:
                conn.execute(
                    "INSERT INTO transport_receipts "
                    "(event_ref, payload_hash, schema_version, sink_id, receipt_json) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (event_ref, payload_hash, schema_version, self.sink_id, receipt_json),
                )
            else:
                receipt_json = bytes(existing[0])
            conn.commit()
        except ConsumerError:
            if conn.in_transaction:
                conn.rollback()
            raise
        except sqlite3.Error:
            if conn.in_transaction:
                conn.rollback()
            raise ConsumerError("receipt_write_unavailable") from None
        finally:
            conn.close()

        stored_receipt = _read_receipt(self.ledger_db_path, event_ref, payload_hash, self.sink_id)
        if stored_receipt is None:
            raise ConsumerError("receipt_readback_missing")
        try:
            stored_object = json.loads(stored_receipt.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError, RecursionError):
            raise ConsumerError("receipt_invalid") from None
        if (
            not _validate_receipt(stored_object)
            or stored_receipt != receipt_json
            or stored_object.get("event_ref") != event_ref
            or stored_object.get("payload_hash") != payload_hash
            or stored_object.get("sink_id") != self.sink_id
            or stored_object.get("ledger_record_hash") != record_hash
        ):
            raise ConsumerError("receipt_readback_mismatch")
        return ConsumerResult("acknowledged", event_ref, payload_hash, stored_object)
