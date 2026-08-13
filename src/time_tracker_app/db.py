import os
import sqlite3
from datetime import datetime
from pathlib import Path

from time_tracker_app.models import Project, Subtask

ISO_FORMAT = "%Y-%m-%dT%H:%M:%S"


def get_db_path() -> Path:
    override = os.environ.get("TT_DB_PATH")
    if override:
        return Path(override)
    return Path.home() / ".timetracker" / "timetracker.db"


def get_connection(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    init_db(conn)
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS projects (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL UNIQUE
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS subtasks (
            id INTEGER PRIMARY KEY,
            project_id INTEGER NOT NULL REFERENCES projects(id),
            name TEXT NOT NULL,
            UNIQUE (project_id, name)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS time_entries (
            id INTEGER PRIMARY KEY,
            subtask_id INTEGER NOT NULL REFERENCES subtasks(id),
            started_at TEXT NOT NULL,
            ended_at TEXT
        )
        """
    )
    conn.commit()


def format_dt(dt: datetime) -> str:
    return dt.strftime(ISO_FORMAT)


def parse_dt(value: str) -> datetime:
    return datetime.strptime(value, ISO_FORMAT)


def create_project(conn: sqlite3.Connection, name: str) -> Project:
    cursor = conn.execute("INSERT INTO projects (name) VALUES (?)", (name,))
    conn.commit()
    return Project(id=cursor.lastrowid, name=name)


def get_project_by_name(conn: sqlite3.Connection, name: str) -> Project | None:
    row = conn.execute(
        "SELECT id, name FROM projects WHERE name = ?", (name,)
    ).fetchone()
    if row is None:
        return None
    return Project(id=row[0], name=row[1])


def create_subtask(conn: sqlite3.Connection, project_id: int, name: str) -> Subtask:
    cursor = conn.execute(
        "INSERT INTO subtasks (project_id, name) VALUES (?, ?)",
        (project_id, name),
    )
    conn.commit()
    return Subtask(id=cursor.lastrowid, project_id=project_id, name=name)


def get_subtask_by_name(
    conn: sqlite3.Connection, project_id: int, name: str
) -> Subtask | None:
    row = conn.execute(
        "SELECT id, project_id, name FROM subtasks WHERE project_id = ? AND name = ?",
        (project_id, name),
    ).fetchone()
    if row is None:
        return None
    return Subtask(id=row[0], project_id=row[1], name=row[2])
