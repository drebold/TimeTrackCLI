import os
import sqlite3
from datetime import datetime
from pathlib import Path

from time_tracker_app.models import Project, Subtask, TimeEntry, TimeEntryView

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


def get_running_entry(conn: sqlite3.Connection) -> TimeEntry | None:
    row = conn.execute(
        "SELECT id, subtask_id, started_at, ended_at FROM time_entries "
        "WHERE ended_at IS NULL"
    ).fetchone()
    if row is None:
        return None
    return TimeEntry(id=row[0], subtask_id=row[1], started_at=row[2], ended_at=row[3])


def get_entry(conn: sqlite3.Connection, entry_id: int) -> TimeEntry | None:
    row = conn.execute(
        "SELECT id, subtask_id, started_at, ended_at FROM time_entries WHERE id = ?",
        (entry_id,),
    ).fetchone()
    if row is None:
        return None
    return TimeEntry(id=row[0], subtask_id=row[1], started_at=row[2], ended_at=row[3])


def start_timer(conn: sqlite3.Connection, subtask_id: int, at: datetime) -> TimeEntry:
    running = get_running_entry(conn)
    if running is not None:
        conn.execute(
            "UPDATE time_entries SET ended_at = ? WHERE id = ?",
            (format_dt(at), running.id),
        )
    cursor = conn.execute(
        "INSERT INTO time_entries (subtask_id, started_at) VALUES (?, ?)",
        (subtask_id, format_dt(at)),
    )
    conn.commit()
    return TimeEntry(
        id=cursor.lastrowid, subtask_id=subtask_id, started_at=format_dt(at), ended_at=None
    )


def stop_timer(conn: sqlite3.Connection, at: datetime) -> TimeEntry | None:
    running = get_running_entry(conn)
    if running is None:
        return None
    conn.execute(
        "UPDATE time_entries SET ended_at = ? WHERE id = ?",
        (format_dt(at), running.id),
    )
    conn.commit()
    running.ended_at = format_dt(at)
    return running


def list_entries(conn: sqlite3.Connection) -> list[TimeEntryView]:
    rows = conn.execute(
        """
        SELECT time_entries.id, projects.name, subtasks.name,
               time_entries.started_at, time_entries.ended_at
        FROM time_entries
        JOIN subtasks ON subtasks.id = time_entries.subtask_id
        JOIN projects ON projects.id = subtasks.project_id
        ORDER BY time_entries.started_at DESC
        """
    ).fetchall()
    return [
        TimeEntryView(
            id=row[0],
            project_name=row[1],
            subtask_name=row[2],
            started_at=row[3],
            ended_at=row[4],
        )
        for row in rows
    ]


def get_subtask_project_names(conn: sqlite3.Connection, subtask_id: int) -> tuple[str, str]:
    row = conn.execute(
        """
        SELECT projects.name, subtasks.name
        FROM subtasks
        JOIN projects ON projects.id = subtasks.project_id
        WHERE subtasks.id = ?
        """,
        (subtask_id,),
    ).fetchone()
    return row[0], row[1]


class EditError(ValueError):
    pass


def update_entry(
    conn: sqlite3.Connection,
    entry_id: int,
    start: datetime | None = None,
    end: datetime | None = None,
) -> TimeEntry:
    entry = get_entry(conn, entry_id)
    if entry is None:
        raise EditError(f"No entry with id {entry_id}")

    new_start = format_dt(start) if start is not None else entry.started_at
    new_end = format_dt(end) if end is not None else entry.ended_at

    if new_end is not None and parse_dt(new_start) >= parse_dt(new_end):
        raise EditError("start must be before end")

    conn.execute(
        "UPDATE time_entries SET started_at = ?, ended_at = ? WHERE id = ?",
        (new_start, new_end, entry_id),
    )
    conn.commit()
    return TimeEntry(id=entry_id, subtask_id=entry.subtask_id, started_at=new_start, ended_at=new_end)
