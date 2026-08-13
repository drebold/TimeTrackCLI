# CLI Time Tracker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first working version of the `tt` CLI time tracker: `start`/`stop`/`status`/`list`/`edit` commands backed by SQLite, enforcing a single active timer app-wide, per `docs/superpowers/specs/2026-08-13-cli-time-tracker-design.md`.

**Architecture:** A small modular package under `src/time_tracker_app/`: `models.py` (dataclasses), `db.py` (schema + all SQL), `timeparse.py` (time-string parsing), `cli.py` (Typer commands), wired up via `__init__.py:main`. Each CLI command opens a connection, does its work, and exits — no background process.

**Tech Stack:** Python 3.14, Typer (Click), stdlib `sqlite3`, plain `venv` + `pip` for env/deps, pytest for tests.

**Implementation note (not in spec, needed for testability):** the DB path used by `db.get_db_path()` is `~/.timetracker/timetracker.db` by default, but reads the `TT_DB_PATH` environment variable first if set. Tests set `TT_DB_PATH` to a `tmp_path` file so they never touch the real database, matching the spec's "temporary SQLite file" testing requirement.

**Implementation note (env tooling):** `uv` is blocked by company IT policy on this machine, so the design's original `uv`-based workflow is replaced with a plain `venv` + `pip`. The worktree's `.venv` is already created and has the project installed in editable mode (`pip install -e . pytest`), so `typer` and `pytest` are available. Run all commands below via the venv's interpreter directly — on Windows PowerShell that's `.\.venv\Scripts\python.exe -m pytest ...` (not `uv run pytest ...`), and `.\.venv\Scripts\tt.exe` (not `uv run tt`) for the installed console script.

---

## File Structure

- `src/time_tracker_app/models.py` — `Project`, `Subtask`, `TimeEntry`, `TimeEntryView` dataclasses
- `src/time_tracker_app/db.py` — DB path resolution, connection/schema setup, all queries (projects, subtasks, timer start/stop, list, edit)
- `src/time_tracker_app/timeparse.py` — parses `HH:MM` / `YYYY-MM-DD HH:MM` strings into `datetime`
- `src/time_tracker_app/cli.py` — Typer app: `start`, `stop`, `status`, `list`, `edit` commands
- `src/time_tracker_app/__init__.py` — `main()` entry point, wires to `cli.app`
- `tests/conftest.py` — shared `conn` (raw DB) and `cli_env` (env var for CLI tests) fixtures
- `tests/test_db.py` — schema, project/subtask CRUD, timer, list, edit tests
- `tests/test_timeparse.py` — time parsing tests
- `tests/test_cli.py` — end-to-end CLI command tests via `typer.testing.CliRunner`

---

### Task 1: DB schema, connection, and data models

**Files:**
- Create: `src/time_tracker_app/models.py`
- Create: `src/time_tracker_app/db.py`
- Create: `tests/conftest.py`
- Test: `tests/test_db.py`

- [ ] **Step 1: Confirm pytest is installed**

pytest and the project (editable) are already installed into the worktree's `.venv` as part of environment setup. Confirm with:

```powershell
.\.venv\Scripts\python.exe -m pytest --version
```

If this fails (e.g. a fresh worktree without a `.venv` yet), create one and install:

```powershell
C:\Users\dre\AppData\Local\Python\pythoncore-3.14-64\python.exe -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e . pytest
```

- [ ] **Step 2: Create the data model dataclasses**

`src/time_tracker_app/models.py`:

```python
from dataclasses import dataclass


@dataclass
class Project:
    id: int
    name: str


@dataclass
class Subtask:
    id: int
    project_id: int
    name: str


@dataclass
class TimeEntry:
    id: int
    subtask_id: int
    started_at: str  # ISO 8601, e.g. "2026-08-13T09:00:00"
    ended_at: str | None  # None while running


@dataclass
class TimeEntryView:
    id: int
    project_name: str
    subtask_name: str
    started_at: str
    ended_at: str | None
```

- [ ] **Step 3: Write the shared test fixture**

`tests/conftest.py`:

```python
import pytest

from time_tracker_app import db


@pytest.fixture
def conn(tmp_path):
    db_path = tmp_path / "test.db"
    connection = db.get_connection(db_path)
    yield connection
    connection.close()


@pytest.fixture
def cli_env(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("TT_DB_PATH", str(db_path))
    return db_path
```

- [ ] **Step 4: Write the failing test**

`tests/test_db.py`:

```python
def test_init_db_creates_tables(conn):
    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert {"projects", "subtasks", "time_entries"} <= tables
```

- [ ] **Step 5: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_db.py::test_init_db_creates_tables -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'time_tracker_app.db'` or similar — `db.py` doesn't exist yet)

- [ ] **Step 6: Implement `db.py` schema and connection setup**

`src/time_tracker_app/db.py`:

```python
import os
import sqlite3
from datetime import datetime
from pathlib import Path

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
```

- [ ] **Step 7: Run test to verify it passes**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_db.py::test_init_db_creates_tables -v`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add src/time_tracker_app/models.py src/time_tracker_app/db.py tests/conftest.py tests/test_db.py pyproject.toml uv.lock
git commit -m "feat: add DB schema, connection setup, and data models"
```

---

### Task 2: Project and subtask CRUD

**Files:**
- Modify: `src/time_tracker_app/db.py`
- Test: `tests/test_db.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_db.py`:

```python
from time_tracker_app import db


def test_create_and_get_project(conn):
    created = db.create_project(conn, "ProjectX")
    fetched = db.get_project_by_name(conn, "ProjectX")
    assert fetched is not None
    assert fetched.id == created.id
    assert fetched.name == "ProjectX"


def test_get_project_by_name_missing_returns_none(conn):
    assert db.get_project_by_name(conn, "Nope") is None


def test_subtask_names_unique_per_project_not_globally(conn):
    project_a = db.create_project(conn, "ProjectA")
    project_b = db.create_project(conn, "ProjectB")

    subtask_a = db.create_subtask(conn, project_a.id, "Design")
    subtask_b = db.create_subtask(conn, project_b.id, "Design")

    assert subtask_a.id != subtask_b.id
    assert db.get_subtask_by_name(conn, project_a.id, "Design").id == subtask_a.id
    assert db.get_subtask_by_name(conn, project_b.id, "Design").id == subtask_b.id


def test_get_subtask_by_name_missing_returns_none(conn):
    project = db.create_project(conn, "ProjectX")
    assert db.get_subtask_by_name(conn, project.id, "Nope") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_db.py -v`
Expected: FAIL (`AttributeError: module 'time_tracker_app.db' has no attribute 'create_project'`)

- [ ] **Step 3: Implement CRUD functions**

Append to `src/time_tracker_app/db.py`:

```python
from time_tracker_app.models import Project, Subtask


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
```

Add the import line (`from time_tracker_app.models import Project, Subtask`) near the top of `db.py` with the other imports, not inline mid-file.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_db.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add src/time_tracker_app/db.py tests/test_db.py
git commit -m "feat: add project and subtask CRUD"
```

---

### Task 3: Timer start/stop with single-active-timer enforcement

**Files:**
- Modify: `src/time_tracker_app/db.py`
- Test: `tests/test_db.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_db.py`:

```python
from datetime import datetime


def _make_subtask(conn, project_name="ProjectX", subtask_name="Task1"):
    project = db.create_project(conn, project_name)
    return db.create_subtask(conn, project.id, subtask_name)


def test_get_running_entry_none_when_nothing_started(conn):
    assert db.get_running_entry(conn) is None


def test_start_timer_creates_running_entry(conn):
    subtask = _make_subtask(conn)
    at = datetime(2026, 8, 13, 9, 0, 0)

    entry = db.start_timer(conn, subtask.id, at)

    assert entry.subtask_id == subtask.id
    assert entry.ended_at is None
    running = db.get_running_entry(conn)
    assert running.id == entry.id


def test_starting_new_timer_closes_previous_one(conn):
    subtask = _make_subtask(conn)
    first_start = datetime(2026, 8, 13, 9, 0, 0)
    second_start = datetime(2026, 8, 13, 10, 0, 0)

    first = db.start_timer(conn, subtask.id, first_start)
    second = db.start_timer(conn, subtask.id, second_start)

    running = db.get_running_entry(conn)
    assert running.id == second.id

    closed = db.get_entry(conn, first.id)
    assert closed.ended_at == db.format_dt(second_start)


def test_stop_timer_closes_running_entry(conn):
    subtask = _make_subtask(conn)
    start_at = datetime(2026, 8, 13, 9, 0, 0)
    stop_at = datetime(2026, 8, 13, 9, 30, 0)

    entry = db.start_timer(conn, subtask.id, start_at)
    stopped = db.stop_timer(conn, stop_at)

    assert stopped.id == entry.id
    assert stopped.ended_at == db.format_dt(stop_at)
    assert db.get_running_entry(conn) is None


def test_stop_timer_returns_none_when_nothing_running(conn):
    assert db.stop_timer(conn, datetime(2026, 8, 13, 9, 0, 0)) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_db.py -v`
Expected: FAIL (`AttributeError: module 'time_tracker_app.db' has no attribute 'get_running_entry'`)

- [ ] **Step 3: Implement timer functions**

Append to `src/time_tracker_app/db.py` (and add `TimeEntry` to the existing models import):

```python
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
```

Update the models import line at the top of `db.py` to:
`from time_tracker_app.models import Project, Subtask, TimeEntry`

- [ ] **Step 4: Run tests to verify they pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_db.py -v`
Expected: PASS (10 tests)

- [ ] **Step 5: Commit**

```bash
git add src/time_tracker_app/db.py tests/test_db.py
git commit -m "feat: add timer start/stop with single-active-timer enforcement"
```

---

### Task 4: List entries and subtask/project name lookup

**Files:**
- Modify: `src/time_tracker_app/db.py`
- Test: `tests/test_db.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_db.py`:

```python
def test_list_entries_empty(conn):
    assert db.list_entries(conn) == []


def test_list_entries_most_recent_first_with_names(conn):
    subtask = _make_subtask(conn, "ProjectX", "Task1")
    db.start_timer(conn, subtask.id, datetime(2026, 8, 13, 9, 0, 0))
    db.stop_timer(conn, datetime(2026, 8, 13, 9, 30, 0))
    db.start_timer(conn, subtask.id, datetime(2026, 8, 13, 10, 0, 0))
    db.stop_timer(conn, datetime(2026, 8, 13, 10, 15, 0))

    entries = db.list_entries(conn)

    assert len(entries) == 2
    assert entries[0].started_at == db.format_dt(datetime(2026, 8, 13, 10, 0, 0))
    assert entries[1].started_at == db.format_dt(datetime(2026, 8, 13, 9, 0, 0))
    assert entries[0].project_name == "ProjectX"
    assert entries[0].subtask_name == "Task1"


def test_get_subtask_project_names(conn):
    subtask = _make_subtask(conn, "ProjectX", "Task1")
    project_name, subtask_name = db.get_subtask_project_names(conn, subtask.id)
    assert project_name == "ProjectX"
    assert subtask_name == "Task1"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_db.py -v`
Expected: FAIL (`AttributeError: module 'time_tracker_app.db' has no attribute 'list_entries'`)

- [ ] **Step 3: Implement list/lookup functions**

Append to `src/time_tracker_app/db.py` (add `TimeEntryView` to the models import):

```python
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
```

Update the models import line at the top of `db.py` to:
`from time_tracker_app.models import Project, Subtask, TimeEntry, TimeEntryView`

- [ ] **Step 4: Run tests to verify they pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_db.py -v`
Expected: PASS (13 tests)

- [ ] **Step 5: Commit**

```bash
git add src/time_tracker_app/db.py tests/test_db.py
git commit -m "feat: add list_entries and subtask/project name lookup"
```

---

### Task 5: Edit entry with validation

**Files:**
- Modify: `src/time_tracker_app/db.py`
- Test: `tests/test_db.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_db.py`:

```python
import pytest


def test_update_entry_changes_end_time(conn):
    subtask = _make_subtask(conn)
    entry = db.start_timer(conn, subtask.id, datetime(2026, 8, 13, 9, 0, 0))
    new_end = datetime(2026, 8, 13, 9, 45, 0)

    updated = db.update_entry(conn, entry.id, end=new_end)

    assert updated.ended_at == db.format_dt(new_end)
    assert db.get_entry(conn, entry.id).ended_at == db.format_dt(new_end)


def test_update_entry_changes_start_time(conn):
    subtask = _make_subtask(conn)
    entry = db.start_timer(conn, subtask.id, datetime(2026, 8, 13, 9, 0, 0))
    new_start = datetime(2026, 8, 13, 8, 30, 0)

    updated = db.update_entry(conn, entry.id, start=new_start)

    assert updated.started_at == db.format_dt(new_start)


def test_update_entry_rejects_start_after_end(conn):
    subtask = _make_subtask(conn)
    entry = db.start_timer(conn, subtask.id, datetime(2026, 8, 13, 9, 0, 0))
    db.stop_timer(conn, datetime(2026, 8, 13, 9, 30, 0))

    with pytest.raises(db.EditError):
        db.update_entry(conn, entry.id, start=datetime(2026, 8, 13, 10, 0, 0))


def test_update_entry_rejects_start_equal_end(conn):
    subtask = _make_subtask(conn)
    same = datetime(2026, 8, 13, 9, 0, 0)
    entry = db.start_timer(conn, subtask.id, same)

    with pytest.raises(db.EditError):
        db.update_entry(conn, entry.id, end=same)


def test_update_entry_missing_id_raises(conn):
    with pytest.raises(db.EditError):
        db.update_entry(conn, 999, end=datetime(2026, 8, 13, 9, 0, 0))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_db.py -v`
Expected: FAIL (`AttributeError: module 'time_tracker_app.db' has no attribute 'update_entry'`)

- [ ] **Step 3: Implement `update_entry` and `EditError`**

Append to `src/time_tracker_app/db.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_db.py -v`
Expected: PASS (18 tests)

- [ ] **Step 5: Commit**

```bash
git add src/time_tracker_app/db.py tests/test_db.py
git commit -m "feat: add entry editing with start/end validation"
```

---

### Task 6: Time input parsing

**Files:**
- Create: `src/time_tracker_app/timeparse.py`
- Test: `tests/test_timeparse.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_timeparse.py`:

```python
from datetime import datetime

import pytest

from time_tracker_app.timeparse import TimeParseError, parse_time_input


def test_parses_hh_mm_using_now_date():
    now = datetime(2026, 8, 13, 12, 0, 0)
    result = parse_time_input("09:30", now)
    assert result == datetime(2026, 8, 13, 9, 30, 0)


def test_parses_full_datetime():
    now = datetime(2026, 8, 13, 12, 0, 0)
    result = parse_time_input("2026-08-10 14:15", now)
    assert result == datetime(2026, 8, 10, 14, 15, 0)


def test_raises_on_unparseable_input():
    now = datetime(2026, 8, 13, 12, 0, 0)
    with pytest.raises(TimeParseError):
        parse_time_input("not a time", now)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_timeparse.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'time_tracker_app.timeparse'`)

- [ ] **Step 3: Implement `timeparse.py`**

`src/time_tracker_app/timeparse.py`:

```python
from datetime import datetime


class TimeParseError(ValueError):
    pass


def parse_time_input(value: str, now: datetime) -> datetime:
    value = value.strip()
    for fmt in ("%Y-%m-%d %H:%M", "%H:%M"):
        try:
            parsed = datetime.strptime(value, fmt)
        except ValueError:
            continue
        if fmt == "%H:%M":
            parsed = parsed.replace(year=now.year, month=now.month, day=now.day)
        return parsed
    raise TimeParseError(f"Could not parse time: {value!r}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_timeparse.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add src/time_tracker_app/timeparse.py tests/test_timeparse.py
git commit -m "feat: add time input parsing for HH:MM and full-datetime forms"
```

---

### Task 7: CLI `start` command

**Files:**
- Create: `src/time_tracker_app/cli.py`
- Modify: `src/time_tracker_app/__init__.py`
- Create: `src/time_tracker_app/__main__.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_cli.py`:

```python
from typer.testing import CliRunner

from time_tracker_app.cli import app
from time_tracker_app import db

runner = CliRunner()


def test_start_creates_project_and_subtask_when_confirmed(cli_env):
    result = runner.invoke(app, ["start", "ProjectX", "Task1"], input="y\ny\n")

    assert result.exit_code == 0
    assert "Started timer on ProjectX/Task1" in result.output

    conn = db.get_connection(cli_env)
    running = db.get_running_entry(conn)
    assert running is not None


def test_start_aborts_when_project_creation_declined(cli_env):
    result = runner.invoke(app, ["start", "ProjectX", "Task1"], input="n\n")

    assert result.exit_code == 1
    conn = db.get_connection(cli_env)
    assert db.get_project_by_name(conn, "ProjectX") is None


def test_start_does_not_prompt_for_existing_project_and_subtask(cli_env):
    conn = db.get_connection(cli_env)
    project = db.create_project(conn, "ProjectX")
    db.create_subtask(conn, project.id, "Task1")

    result = runner.invoke(app, ["start", "ProjectX", "Task1"])

    assert result.exit_code == 0
    assert "Started timer on ProjectX/Task1" in result.output


def test_start_closes_previously_running_timer(cli_env):
    conn = db.get_connection(cli_env)
    project = db.create_project(conn, "ProjectX")
    db.create_subtask(conn, project.id, "Task1")
    db.create_subtask(conn, project.id, "Task2")

    runner.invoke(app, ["start", "ProjectX", "Task1"])
    runner.invoke(app, ["start", "ProjectX", "Task2"])

    conn = db.get_connection(cli_env)
    running = db.get_running_entry(conn)
    _, subtask_name = db.get_subtask_project_names(conn, running.subtask_id)
    assert subtask_name == "Task2"
    assert len(db.list_entries(conn)) == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_cli.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'time_tracker_app.cli'`)

- [ ] **Step 3: Implement `cli.py` with the `start` command**

`src/time_tracker_app/cli.py`:

```python
from datetime import datetime

import typer

from time_tracker_app import db
from time_tracker_app.timeparse import TimeParseError, parse_time_input

app = typer.Typer()


def _get_or_create_project(conn, name: str) -> db.Project | None:
    project = db.get_project_by_name(conn, name)
    if project is not None:
        return project
    if not typer.confirm(f"Project '{name}' doesn't exist. Create it?"):
        return None
    return db.create_project(conn, name)


def _get_or_create_subtask(conn, project_id: int, project_name: str, name: str) -> db.Subtask | None:
    subtask = db.get_subtask_by_name(conn, project_id, name)
    if subtask is not None:
        return subtask
    if not typer.confirm(f"Subtask '{name}' doesn't exist under '{project_name}'. Create it?"):
        return None
    return db.create_subtask(conn, project_id, name)


@app.command()
def start(project: str, subtask: str) -> None:
    """Start the timer on a subtask, creating project/subtask if confirmed."""
    conn = db.get_connection(db.get_db_path())
    proj = _get_or_create_project(conn, project)
    if proj is None:
        typer.echo("Aborted: project not created.")
        raise typer.Exit(code=1)
    sub = _get_or_create_subtask(conn, proj.id, proj.name, subtask)
    if sub is None:
        typer.echo("Aborted: subtask not created.")
        raise typer.Exit(code=1)
    db.start_timer(conn, sub.id, datetime.now())
    typer.echo(f"Started timer on {proj.name}/{sub.name}")
```

`src/time_tracker_app/__init__.py`:

```python
from time_tracker_app.cli import app


def main() -> None:
    app()
```

`src/time_tracker_app/__main__.py` (lets the app run as `python -m time_tracker_app`, useful when the installed `tt` console-script launcher can't run, e.g. under IT-policy application allowlisting that blocks unsigned generated `.exe` launchers but not `python.exe` itself):

```python
from time_tracker_app import main

main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_cli.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add src/time_tracker_app/cli.py src/time_tracker_app/__init__.py tests/test_cli.py
git commit -m "feat: add CLI start command with confirm-to-create"
```

---

### Task 8: CLI `stop` command

**Files:**
- Modify: `src/time_tracker_app/cli.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_cli.py`:

```python
def test_stop_closes_running_timer(cli_env):
    runner.invoke(app, ["start", "ProjectX", "Task1"], input="y\ny\n")

    result = runner.invoke(app, ["stop"])

    assert result.exit_code == 0
    assert "Stopped timer" in result.output
    conn = db.get_connection(cli_env)
    assert db.get_running_entry(conn) is None


def test_stop_with_no_timer_running_is_not_an_error(cli_env):
    result = runner.invoke(app, ["stop"])

    assert result.exit_code == 0
    assert "No timer running" in result.output


def test_stop_with_at_backdates_stop_time(cli_env):
    runner.invoke(app, ["start", "ProjectX", "Task1"], input="y\ny\n")

    result = runner.invoke(app, ["stop", "--at", "08:00"])

    assert result.exit_code == 0
    conn = db.get_connection(cli_env)
    entries = db.list_entries(conn)
    assert entries[0].ended_at.endswith("08:00:00")


def test_stop_with_unparseable_at_is_an_error(cli_env):
    runner.invoke(app, ["start", "ProjectX", "Task1"], input="y\ny\n")

    result = runner.invoke(app, ["stop", "--at", "not-a-time"])

    assert result.exit_code == 1
    conn = db.get_connection(cli_env)
    assert db.get_running_entry(conn) is not None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_cli.py -v`
Expected: FAIL (`Error: No such command 'stop'`)

- [ ] **Step 3: Implement the `stop` command**

Append to `src/time_tracker_app/cli.py`:

```python
@app.command()
def stop(at: str = typer.Option(None, "--at", help="Backdate the stop time, e.g. '14:30'")) -> None:
    """Stop the running timer."""
    conn = db.get_connection(db.get_db_path())
    now = datetime.now()
    if at is not None:
        try:
            stop_time = parse_time_input(at, now)
        except TimeParseError as e:
            typer.echo(f"Error: {e}")
            raise typer.Exit(code=1)
    else:
        stop_time = now
    entry = db.stop_timer(conn, stop_time)
    if entry is None:
        typer.echo("No timer running")
        return
    typer.echo(f"Stopped timer (entry {entry.id})")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_cli.py -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Commit**

```bash
git add src/time_tracker_app/cli.py tests/test_cli.py
git commit -m "feat: add CLI stop command with --at backdating"
```

---

### Task 9: CLI `status` command

**Files:**
- Modify: `src/time_tracker_app/cli.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_cli.py`:

```python
def test_status_shows_running_timer(cli_env):
    runner.invoke(app, ["start", "ProjectX", "Task1"], input="y\ny\n")

    result = runner.invoke(app, ["status"])

    assert result.exit_code == 0
    assert "ProjectX/Task1" in result.output


def test_status_shows_no_timer_running(cli_env):
    result = runner.invoke(app, ["status"])

    assert result.exit_code == 0
    assert "No timer running" in result.output
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_cli.py -v`
Expected: FAIL (`Error: No such command 'status'`)

- [ ] **Step 3: Implement the `status` command**

Append to `src/time_tracker_app/cli.py`:

```python
@app.command()
def status() -> None:
    """Show the currently running timer, if any."""
    conn = db.get_connection(db.get_db_path())
    running = db.get_running_entry(conn)
    if running is None:
        typer.echo("No timer running")
        return
    project_name, subtask_name = db.get_subtask_project_names(conn, running.subtask_id)
    started = db.parse_dt(running.started_at)
    elapsed = datetime.now() - started
    typer.echo(f"Running: {project_name}/{subtask_name} ({elapsed})")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_cli.py -v`
Expected: PASS (10 tests)

- [ ] **Step 5: Commit**

```bash
git add src/time_tracker_app/cli.py tests/test_cli.py
git commit -m "feat: add CLI status command"
```

---

### Task 10: CLI `list` command

**Files:**
- Modify: `src/time_tracker_app/cli.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_cli.py`:

```python
def test_list_shows_no_entries_message(cli_env):
    result = runner.invoke(app, ["list"])

    assert result.exit_code == 0
    assert "No entries yet" in result.output


def test_list_shows_entries_most_recent_first(cli_env):
    runner.invoke(app, ["start", "ProjectX", "Task1"], input="y\ny\n")
    runner.invoke(app, ["stop"])
    runner.invoke(app, ["start", "ProjectX", "Task2"], input="y\n")

    result = runner.invoke(app, ["list"])

    assert result.exit_code == 0
    lines = [line for line in result.output.splitlines() if "ProjectX" in line]
    assert len(lines) == 2
    assert "Task2" in lines[0]
    assert "Task1" in lines[1]
    assert "running" in lines[0]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_cli.py -v`
Expected: FAIL (`Error: No such command 'list'`)

- [ ] **Step 3: Implement the `list` command**

Append to `src/time_tracker_app/cli.py`:

```python
@app.command(name="list")
def list_entries_cmd() -> None:
    """List past and current time entries, most recent first."""
    conn = db.get_connection(db.get_db_path())
    entries = db.list_entries(conn)
    if not entries:
        typer.echo("No entries yet")
        return
    for entry in entries:
        end = entry.ended_at if entry.ended_at is not None else "running"
        typer.echo(f"[{entry.id}] {entry.project_name}/{entry.subtask_name}  {entry.started_at} -> {end}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_cli.py -v`
Expected: PASS (12 tests)

- [ ] **Step 5: Commit**

```bash
git add src/time_tracker_app/cli.py tests/test_cli.py
git commit -m "feat: add CLI list command"
```

---

### Task 11: CLI `edit` command

**Files:**
- Modify: `src/time_tracker_app/cli.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_cli.py`:

```python
def test_edit_updates_end_time(cli_env):
    runner.invoke(app, ["start", "ProjectX", "Task1"], input="y\ny\n")
    runner.invoke(app, ["stop"])
    conn = db.get_connection(cli_env)
    entry_id = db.list_entries(conn)[0].id

    result = runner.invoke(app, ["edit", str(entry_id), "--end", "17:00"])

    assert result.exit_code == 0
    assert f"Updated entry {entry_id}" in result.output
    conn = db.get_connection(cli_env)
    assert db.list_entries(conn)[0].ended_at.endswith("17:00:00")


def test_edit_requires_start_or_end(cli_env):
    runner.invoke(app, ["start", "ProjectX", "Task1"], input="y\ny\n")
    conn = db.get_connection(cli_env)
    entry_id = db.get_running_entry(conn).id

    result = runner.invoke(app, ["edit", str(entry_id)])

    assert result.exit_code == 1
    assert "provide --start and/or --end" in result.output


def test_edit_rejects_start_after_end(cli_env):
    runner.invoke(app, ["start", "ProjectX", "Task1"], input="y\ny\n")
    runner.invoke(app, ["stop", "--at", "09:30"])
    conn = db.get_connection(cli_env)
    entry_id = db.list_entries(conn)[0].id

    result = runner.invoke(app, ["edit", str(entry_id), "--start", "10:00"])

    assert result.exit_code == 1
    assert "start must be before end" in result.output


def test_edit_unparseable_time_is_an_error(cli_env):
    runner.invoke(app, ["start", "ProjectX", "Task1"], input="y\ny\n")
    conn = db.get_connection(cli_env)
    entry_id = db.get_running_entry(conn).id

    result = runner.invoke(app, ["edit", str(entry_id), "--end", "not-a-time"])

    assert result.exit_code == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_cli.py -v`
Expected: FAIL (`Error: No such command 'edit'`)

- [ ] **Step 3: Implement the `edit` command**

Append to `src/time_tracker_app/cli.py`:

```python
@app.command()
def edit(
    entry_id: int,
    start: str = typer.Option(None, "--start", help="New start time, e.g. '09:00'"),
    end: str = typer.Option(None, "--end", help="New end time, e.g. '17:00'"),
) -> None:
    """Fix the start and/or end time of an existing entry."""
    if start is None and end is None:
        typer.echo("Error: provide --start and/or --end")
        raise typer.Exit(code=1)

    conn = db.get_connection(db.get_db_path())
    now = datetime.now()
    try:
        start_dt = parse_time_input(start, now) if start is not None else None
        end_dt = parse_time_input(end, now) if end is not None else None
    except TimeParseError as e:
        typer.echo(f"Error: {e}")
        raise typer.Exit(code=1)

    try:
        entry = db.update_entry(conn, entry_id, start=start_dt, end=end_dt)
    except db.EditError as e:
        typer.echo(f"Error: {e}")
        raise typer.Exit(code=1)

    typer.echo(f"Updated entry {entry.id}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_cli.py -v`
Expected: PASS (16 tests)

- [ ] **Step 5: Commit**

```bash
git add src/time_tracker_app/cli.py tests/test_cli.py
git commit -m "feat: add CLI edit command"
```

---

### Task 12: Full test suite and manual smoke test

**Files:**
- None (verification only)

- [ ] **Step 1: Run the full test suite**

Run: `.\.venv\Scripts\python.exe -m pytest -v`
Expected: PASS (all tests across `test_db.py`, `test_timeparse.py`, `test_cli.py`)

- [ ] **Step 2: Manual smoke test against a throwaway DB**

The installed `tt.exe` console-script launcher may be blocked by IT-policy application allowlisting (unsigned generated `.exe`). Use `python -m time_tracker_app` instead, which runs through the already-trusted `python.exe`:

```powershell
$env:TT_DB_PATH = "$env:TEMP\tt-smoke.db"
.\.venv\Scripts\python.exe -m time_tracker_app start Demo FirstTask
.\.venv\Scripts\python.exe -m time_tracker_app status
.\.venv\Scripts\python.exe -m time_tracker_app stop
.\.venv\Scripts\python.exe -m time_tracker_app list
```

If `tt.exe` happens to work in your environment, either invocation is fine — they run the same code.

Expected: `start` prompts to create Demo/FirstTask (answer `y` twice), `status` shows it running, `stop` closes it, `list` shows one finished entry.

- [ ] **Step 3: Commit if any fixups were needed**

If Step 1 or Step 2 surfaced a bug, fix it, re-run the affected task's tests, then:

```bash
git add -A
git commit -m "fix: address issue found in full-suite smoke test"
```

If nothing needed fixing, skip this step — nothing to commit.

---

## Self-Review Notes

- **Spec coverage:** `start`/`stop`/`status`/`list`/`edit` all covered (Tasks 7–11); auto-create-with-confirm (Task 7); single-active-timer enforcement (Task 3, exercised again in Task 7); per-project-unique subtask names (Task 2); `--at`/`--start`/`--end` time parsing incl. error path (Task 6, used in Tasks 8 & 11); `start >= end` rejection (Task 5, exercised in Task 11); DB location and no-background-process behavior (Task 1 design, inherent in every command opening its own connection); testing with temp DB files (`conn` and `cli_env` fixtures, Task 1).
- **Placeholder scan:** none found — every step has complete, concrete code.
- **Type consistency:** `Project`, `Subtask`, `TimeEntry`, `TimeEntryView` field names used consistently from Task 1 through Task 11; `db.get_db_path`, `db.get_connection`, `db.start_timer`, `db.stop_timer`, `db.list_entries`, `db.update_entry`, `db.EditError`, `db.get_subtask_project_names`, and `timeparse.parse_time_input`/`TimeParseError` are each defined once and referenced with matching names/signatures everywhere they're used.
