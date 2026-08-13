import os
import sqlite3
from datetime import date, datetime, time
from pathlib import Path

from time_tracker_app.models import (
    Project,
    Subtask,
    TimeEntry,
    TimeEntryView,
    WeekReportRow,
)

ISO_FORMAT = "%Y-%m-%dT%H:%M:%S"

DAYS_PER_WEEK = 7


class EditError(ValueError):
    pass


class OverlapError(ValueError):
    pass


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
            name TEXT NOT NULL UNIQUE,
            case_number TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS subtasks (
            id INTEGER PRIMARY KEY,
            project_id INTEGER NOT NULL REFERENCES projects(id),
            name TEXT NOT NULL,
            case_task TEXT,
            work_type TEXT,
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
    _migrate_subtasks_columns(conn)
    _migrate_projects_columns(conn)
    conn.commit()


def _migrate_subtasks_columns(conn: sqlite3.Connection) -> None:
    existing = {row[1] for row in conn.execute("PRAGMA table_info(subtasks)").fetchall()}
    if "case_task" not in existing:
        conn.execute("ALTER TABLE subtasks ADD COLUMN case_task TEXT")
    if "work_type" not in existing:
        conn.execute("ALTER TABLE subtasks ADD COLUMN work_type TEXT")


def _migrate_projects_columns(conn: sqlite3.Connection) -> None:
    existing = {row[1] for row in conn.execute("PRAGMA table_info(projects)").fetchall()}
    if "case_number" not in existing:
        conn.execute("ALTER TABLE projects ADD COLUMN case_number TEXT")


def format_dt(dt: datetime) -> str:
    return dt.strftime(ISO_FORMAT)


def parse_dt(value: str) -> datetime:
    return datetime.strptime(value, ISO_FORMAT)


def create_project(conn: sqlite3.Connection, name: str, case_number: str | None = None) -> Project:
    cursor = conn.execute(
        "INSERT INTO projects (name, case_number) VALUES (?, ?)", (name, case_number)
    )
    conn.commit()
    return Project(id=cursor.lastrowid, name=name, case_number=case_number)


def get_project_by_name(conn: sqlite3.Connection, name: str) -> Project | None:
    row = conn.execute(
        "SELECT id, name, case_number FROM projects WHERE name = ?", (name,)
    ).fetchone()
    if row is None:
        return None
    return Project(id=row[0], name=row[1], case_number=row[2])


def get_project(conn: sqlite3.Connection, project_id: int) -> Project | None:
    row = conn.execute(
        "SELECT id, name, case_number FROM projects WHERE id = ?", (project_id,)
    ).fetchone()
    if row is None:
        return None
    return Project(id=row[0], name=row[1], case_number=row[2])


def update_project(
    conn: sqlite3.Connection,
    project_id: int,
    name: str | None = None,
    case_number: str | None = None,
) -> Project:
    project = get_project(conn, project_id)
    if project is None:
        raise EditError(f"No project with id {project_id}")

    new_name = name if name is not None else project.name
    new_case_number = case_number if case_number is not None else project.case_number

    try:
        conn.execute(
            "UPDATE projects SET name = ?, case_number = ? WHERE id = ?",
            (new_name, new_case_number, project_id),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        raise EditError(f"A project named '{new_name}' already exists") from None

    return Project(id=project_id, name=new_name, case_number=new_case_number)


def create_subtask(
    conn: sqlite3.Connection,
    project_id: int,
    name: str,
    case_task: str | None = None,
    work_type: str | None = None,
) -> Subtask:
    cursor = conn.execute(
        "INSERT INTO subtasks (project_id, name, case_task, work_type) VALUES (?, ?, ?, ?)",
        (project_id, name, case_task, work_type),
    )
    conn.commit()
    return Subtask(
        id=cursor.lastrowid,
        project_id=project_id,
        name=name,
        case_task=case_task,
        work_type=work_type,
    )


def get_subtask_by_name(
    conn: sqlite3.Connection, project_id: int, name: str
) -> Subtask | None:
    row = conn.execute(
        "SELECT id, project_id, name, case_task, work_type FROM subtasks "
        "WHERE project_id = ? AND name = ?",
        (project_id, name),
    ).fetchone()
    if row is None:
        return None
    return Subtask(id=row[0], project_id=row[1], name=row[2], case_task=row[3], work_type=row[4])


def get_subtask(conn: sqlite3.Connection, subtask_id: int) -> Subtask | None:
    row = conn.execute(
        "SELECT id, project_id, name, case_task, work_type FROM subtasks WHERE id = ?",
        (subtask_id,),
    ).fetchone()
    if row is None:
        return None
    return Subtask(id=row[0], project_id=row[1], name=row[2], case_task=row[3], work_type=row[4])


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


def find_overlapping_entry(
    conn: sqlite3.Connection,
    start: datetime,
    end: datetime | None,
    exclude_entry_id: int | None = None,
) -> TimeEntry | None:
    """Find an existing entry on `start`'s calendar day that conflicts with [start, end).

    If `end` is None (the candidate entry is still open/running), a conflict is only
    reported when `start` falls inside an already-closed entry's range - we can't know
    yet how far the open entry will eventually extend.

    If `end` is given (the candidate has a fixed range) and an existing entry is itself
    still open/running, that entry is treated as running until now() - it has already
    consumed that time even though its final stop time isn't known yet.
    """
    day = start.date()
    day_start = format_dt(datetime.combine(day, time.min))
    day_end = format_dt(datetime.combine(day, time.max))
    rows = conn.execute(
        "SELECT id, subtask_id, started_at, ended_at FROM time_entries "
        "WHERE started_at >= ? AND started_at <= ?",
        (day_start, day_end),
    ).fetchall()
    for row in rows:
        if exclude_entry_id is not None and row[0] == exclude_entry_id:
            continue
        existing_start = parse_dt(row[2])
        existing_end = parse_dt(row[3]) if row[3] is not None else None
        if end is None:
            if existing_end is not None and existing_start <= start < existing_end:
                return TimeEntry(id=row[0], subtask_id=row[1], started_at=row[2], ended_at=row[3])
        else:
            effective_existing_end = existing_end if existing_end is not None else datetime.now()
            if start < effective_existing_end and existing_start < end:
                return TimeEntry(id=row[0], subtask_id=row[1], started_at=row[2], ended_at=row[3])
    return None


def start_timer(conn: sqlite3.Connection, subtask_id: int, at: datetime) -> TimeEntry:
    conflict = find_overlapping_entry(conn, at, None)
    if conflict is not None:
        raise OverlapError(
            f"{format_dt(at)} overlaps entry {conflict.id} "
            f"({conflict.started_at} -> {conflict.ended_at})"
        )
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
    conflict = find_overlapping_entry(
        conn, parse_dt(running.started_at), at, exclude_entry_id=running.id
    )
    if conflict is not None:
        raise OverlapError(
            f"stopping at {format_dt(at)} would overlap entry {conflict.id} "
            f"({conflict.started_at} -> {conflict.ended_at})"
        )
    conn.execute(
        "UPDATE time_entries SET ended_at = ? WHERE id = ?",
        (format_dt(at), running.id),
    )
    conn.commit()
    running.ended_at = format_dt(at)
    return running


def add_entry(conn: sqlite3.Connection, subtask_id: int, start: datetime, end: datetime) -> TimeEntry:
    """Add a complete (already-closed) entry directly, without touching the running timer."""
    if start >= end:
        raise EditError("start must be before end")

    conflict = find_overlapping_entry(conn, start, end)
    if conflict is not None:
        raise OverlapError(
            f"{format_dt(start)} -> {format_dt(end)} overlaps entry {conflict.id} "
            f"({conflict.started_at} -> {conflict.ended_at})"
        )

    cursor = conn.execute(
        "INSERT INTO time_entries (subtask_id, started_at, ended_at) VALUES (?, ?, ?)",
        (subtask_id, format_dt(start), format_dt(end)),
    )
    conn.commit()
    return TimeEntry(
        id=cursor.lastrowid, subtask_id=subtask_id, started_at=format_dt(start), ended_at=format_dt(end)
    )


def delete_entry(conn: sqlite3.Connection, entry_id: int) -> bool:
    cursor = conn.execute("DELETE FROM time_entries WHERE id = ?", (entry_id,))
    conn.commit()
    return cursor.rowcount > 0


def list_entries(
    conn: sqlite3.Connection,
    start_date: date | None = None,
    end_date: date | None = None,
) -> list[TimeEntryView]:
    query = """
        SELECT time_entries.id, projects.name, subtasks.name,
               time_entries.started_at, time_entries.ended_at
        FROM time_entries
        JOIN subtasks ON subtasks.id = time_entries.subtask_id
        JOIN projects ON projects.id = subtasks.project_id
    """
    params: list[str] = []
    if start_date is not None:
        query += " WHERE time_entries.started_at >= ?"
        params.append(format_dt(datetime.combine(start_date, time.min)))
    if end_date is not None:
        query += " AND" if params else " WHERE"
        query += " time_entries.started_at <= ?"
        params.append(format_dt(datetime.combine(end_date, time.max)))
    query += " ORDER BY time_entries.started_at DESC, time_entries.id DESC"
    rows = conn.execute(query, params).fetchall()
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

    conflict = find_overlapping_entry(
        conn,
        parse_dt(new_start),
        parse_dt(new_end) if new_end is not None else None,
        exclude_entry_id=entry_id,
    )
    if conflict is not None:
        raise OverlapError(
            f"{new_start} -> {new_end} overlaps entry {conflict.id} "
            f"({conflict.started_at} -> {conflict.ended_at})"
        )

    conn.execute(
        "UPDATE time_entries SET started_at = ?, ended_at = ? WHERE id = ?",
        (new_start, new_end, entry_id),
    )
    conn.commit()
    return TimeEntry(id=entry_id, subtask_id=entry.subtask_id, started_at=new_start, ended_at=new_end)


def get_week_report(conn: sqlite3.Connection, monday: date, sunday: date) -> list[WeekReportRow]:
    rows = conn.execute(
        """
        SELECT subtasks.id, projects.case_number, subtasks.case_task, subtasks.work_type,
               subtasks.name, time_entries.started_at, time_entries.ended_at
        FROM time_entries
        JOIN subtasks ON subtasks.id = time_entries.subtask_id
        JOIN projects ON projects.id = subtasks.project_id
        WHERE time_entries.started_at >= ? AND time_entries.started_at <= ?
        ORDER BY projects.name, subtasks.name
        """,
        (
            format_dt(datetime.combine(monday, time.min)),
            format_dt(datetime.combine(sunday, time.max)),
        ),
    ).fetchall()

    now = datetime.now()
    # Keyed by subtask id (not the display strings) - case_number, unlike a
    # project's name, isn't guaranteed unique across projects, so it can't
    # safely stand in as (part of) a grouping key.
    rows_by_subtask: dict[int, list] = {}
    for subtask_id, case_number, case_task, work_type, subtask_name, started_at, ended_at in rows:
        started = parse_dt(started_at)
        ended = parse_dt(ended_at) if ended_at is not None else now
        hours = (ended - started).total_seconds() / 3600
        if subtask_id not in rows_by_subtask:
            rows_by_subtask[subtask_id] = [
                case_number,
                case_task,
                work_type,
                subtask_name,
                [0.0] * DAYS_PER_WEEK,
            ]
        rows_by_subtask[subtask_id][4][started.date().weekday()] += hours

    return [
        WeekReportRow(
            sagsnr=case_number,
            sagsopgave=case_task,
            arbejdstype=work_type,
            beskrivelse=subtask_name,
            hours_by_day=hours_by_day,
        )
        for case_number, case_task, work_type, subtask_name, hours_by_day in rows_by_subtask.values()
    ]
