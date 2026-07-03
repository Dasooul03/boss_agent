from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from config import Config, ensure_data_dirs
from tools import now_iso


def connect() -> sqlite3.Connection:
    ensure_data_dirs()
    conn = sqlite3.connect(Config.app_db_name)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    ensure_data_dirs()
    Path(Config.app_db_name).parent.mkdir(parents=True, exist_ok=True)
    with closing(connect()) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT UNIQUE,
                title TEXT,
                company TEXT,
                salary TEXT,
                city TEXT,
                detail TEXT,
                analysis_json TEXT,
                recommendation TEXT,
                final_action TEXT,
                greeted INTEGER DEFAULT 0,
                resume_sent INTEGER DEFAULT 0,
                hr_replied INTEGER DEFAULT 0,
                error TEXT,
                created_at TEXT,
                updated_at TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS actions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                action_type TEXT NOT NULL,
                status TEXT NOT NULL,
                job_url TEXT,
                company TEXT,
                title TEXT,
                payload_json TEXT,
                result_json TEXT,
                note TEXT,
                created_at TEXT,
                updated_at TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                level TEXT NOT NULL,
                source TEXT NOT NULL,
                message TEXT NOT NULL,
                detail_json TEXT,
                created_at TEXT
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_company_greeted ON jobs(company, greeted)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_updated_at ON jobs(updated_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_actions_status_created_at ON actions(status, created_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_events_created_at ON events(created_at)")
        conn.commit()


def upsert_job(job: dict[str, Any], analysis: dict[str, Any] | None = None, final_action: str = "") -> dict[str, Any]:
    init_db()
    url = job.get("url") or f"{job.get('company', '')}|{job.get('title', '')}|{job.get('salary', '')}"
    current_time = now_iso()
    analysis_json = json.dumps(analysis or {}, ensure_ascii=False)
    with closing(connect()) as conn:
        conn.execute(
            """
            INSERT INTO jobs (
                url, title, company, salary, city, detail, analysis_json,
                recommendation, final_action, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(url) DO UPDATE SET
                title=excluded.title,
                company=excluded.company,
                salary=excluded.salary,
                city=excluded.city,
                detail=excluded.detail,
                analysis_json=excluded.analysis_json,
                recommendation=excluded.recommendation,
                final_action=CASE WHEN excluded.final_action != '' THEN excluded.final_action ELSE jobs.final_action END,
                updated_at=excluded.updated_at
            """,
            (
                url,
                job.get("title", ""),
                job.get("company", ""),
                job.get("salary", ""),
                job.get("city", ""),
                job.get("detail", ""),
                analysis_json,
                (analysis or {}).get("recommendation", ""),
                final_action,
                current_time,
                current_time,
            ),
        )
        conn.commit()
    return get_job(url) or {}


def get_job(url: str) -> dict[str, Any] | None:
    init_db()
    with closing(connect()) as conn:
        row = conn.execute("SELECT * FROM jobs WHERE url = ?", (url,)).fetchone()
    return row_to_dict(row) if row else None


def count_greeted_company(company: str) -> int:
    init_db()
    if not company:
        return 0
    with closing(connect()) as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS count FROM jobs WHERE company = ? AND greeted = 1",
            (company,),
        ).fetchone()
    return int(row["count"]) if row else 0


def update_job_status(
    url: str,
    *,
    final_action: str = "",
    greeted: bool | None = None,
    resume_sent: bool | None = None,
    hr_replied: bool | None = None,
    error: str = "",
) -> dict[str, Any] | None:
    init_db()
    if not url:
        return None
    updates: list[str] = ["updated_at = ?"]
    values: list[Any] = [now_iso()]
    if final_action:
        updates.append("final_action = ?")
        values.append(final_action)
    if greeted is not None:
        updates.append("greeted = ?")
        values.append(1 if greeted else 0)
    if resume_sent is not None:
        updates.append("resume_sent = ?")
        values.append(1 if resume_sent else 0)
    if hr_replied is not None:
        updates.append("hr_replied = ?")
        values.append(1 if hr_replied else 0)
    if error:
        updates.append("error = ?")
        values.append(error)
    values.append(url)
    with closing(connect()) as conn:
        conn.execute(
            f"UPDATE jobs SET {', '.join(updates)} WHERE url = ?",
            values,
        )
        conn.commit()
    return get_job(url)


def create_action(action: dict[str, Any]) -> dict[str, Any]:
    init_db()
    current_time = now_iso()
    with closing(connect()) as conn:
        cursor = conn.execute(
            """
            INSERT INTO actions (
                action_type, status, job_url, company, title, payload_json,
                result_json, note, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                action.get("action_type", ""),
                action.get("status", "pending"),
                action.get("job_url", ""),
                action.get("company", ""),
                action.get("title", ""),
                json.dumps(action.get("payload", {}), ensure_ascii=False),
                json.dumps(action.get("result", {}), ensure_ascii=False),
                action.get("note", ""),
                current_time,
                current_time,
            ),
        )
        conn.commit()
        action_id = cursor.lastrowid
    return get_action(action_id) or {}


def update_action(action_id: int, status: str, note: str = "", result: dict[str, Any] | None = None) -> dict[str, Any]:
    init_db()
    current_time = now_iso()
    with closing(connect()) as conn:
        conn.execute(
            """
            UPDATE actions
            SET status = ?, note = ?, result_json = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                status,
                note,
                json.dumps(result or {}, ensure_ascii=False),
                current_time,
                action_id,
            ),
        )
        conn.commit()
    return get_action(action_id) or {}


def get_action(action_id: int) -> dict[str, Any] | None:
    init_db()
    with closing(connect()) as conn:
        row = conn.execute("SELECT * FROM actions WHERE id = ?", (action_id,)).fetchone()
    return row_to_dict(row) if row else None


def list_pending_actions() -> list[dict[str, Any]]:
    init_db()
    with closing(connect()) as conn:
        rows = conn.execute(
            "SELECT * FROM actions WHERE status = 'pending' ORDER BY created_at DESC"
        ).fetchall()
    return [row_to_dict(row) for row in rows]


def list_history(limit: int = 100, offset: int = 0) -> dict[str, Any]:
    init_db()
    with closing(connect()) as conn:
        jobs = conn.execute(
            "SELECT * FROM jobs ORDER BY updated_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
        actions = conn.execute(
            "SELECT * FROM actions ORDER BY updated_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
    return {
        "jobs": [row_to_dict(row) for row in jobs],
        "actions": [row_to_dict(row) for row in actions],
    }


def list_recent_processed_jobs(limit: int = 500, hours: int = 24) -> list[dict[str, Any]]:
    init_db()
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=max(1, hours))).isoformat()
    with closing(connect()) as conn:
        rows = conn.execute(
            """
            SELECT url, title, company, recommendation, final_action, greeted, updated_at, error
            FROM jobs
            WHERE url != '' AND updated_at >= ?
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (cutoff, limit),
        ).fetchall()
    return [row_to_dict(row) for row in rows]


def create_event(event: dict[str, Any]) -> dict[str, Any]:
    init_db()
    current_time = event.get("time") or now_iso()
    with closing(connect()) as conn:
        cursor = conn.execute(
            """
            INSERT INTO events (
                event_type, level, source, message, detail_json, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                event.get("type", "event"),
                event.get("level", "info"),
                event.get("source", "backend"),
                event.get("message", ""),
                json.dumps(event.get("detail", {}), ensure_ascii=False),
                current_time,
            ),
        )
        conn.commit()
        event_id = cursor.lastrowid
    stored = dict(event)
    stored["id"] = event_id
    return stored


def list_events(limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
    init_db()
    with closing(connect()) as conn:
        rows = conn.execute(
            "SELECT * FROM events ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
    return [row_to_dict(row) for row in rows]


def row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    for key in ("analysis_json", "payload_json", "result_json", "detail_json"):
        if key in data:
            try:
                data[key.replace("_json", "")] = json.loads(data[key] or "{}")
            except json.JSONDecodeError:
                data[key.replace("_json", "")] = {}
            del data[key]
    return data
