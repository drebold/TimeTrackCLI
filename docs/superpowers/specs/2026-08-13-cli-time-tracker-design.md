# CLI Time Tracker — Design

Date: 2026-08-13

## Overview

A Python CLI tool for tracking time against projects and subtasks, per the
core concept in [CLAUDE.md](../../../CLAUDE.md):

- Work is organized into **projects**, each with **subtasks**.
- There is a single timer for the whole app, not one per project or subtask.
- Starting the timer requires attaching it to one subtask (under a project).
- Only one timer can run at a time — starting a new timer stops/finishes
  whatever is currently running.

This is the first build: a working core timer with editing, no reports and
no shell completion yet (see Out of Scope).

## Tech stack

- **Language**: Python
- **CLI framework**: [Typer](https://typer.tiangolo.com/) (pulls in Click)
- **Storage**: SQLite via stdlib `sqlite3`, no ORM
- **Env/packaging**: [uv](https://docs.astral.sh/uv/) — `uv init`, `uv add typer`,
  entry point exposed as a console script (`tt`) via `pyproject.toml`
  `[project.scripts]`, run with `uv run tt ...`
- **Testing**: pytest

## Architecture

Small modular package rather than a single script, so each piece stays
independently readable as features (reports, completion) get added later:

- `db.py` — schema creation and all SQL queries
- `models.py` — simple dataclasses for `Project`, `Subtask`, `TimeEntry`
- `cli.py` — Typer commands, confirm-to-create prompts, single-timer
  enforcement
- `main.py` — entry point wiring the Typer app together

## Data model

SQLite file at `~/.timetracker/timetracker.db` (fixed path under the user's
home directory via `os.path.expanduser`, so the tool behaves the same
regardless of the working directory it's run from).

```sql
CREATE TABLE projects (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE subtasks (
    id INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects(id),
    name TEXT NOT NULL,
    UNIQUE (project_id, name)
);

CREATE TABLE time_entries (
    id INTEGER PRIMARY KEY,
    subtask_id INTEGER NOT NULL REFERENCES subtasks(id),
    started_at TEXT NOT NULL,   -- ISO 8601
    ended_at TEXT               -- ISO 8601, NULL while running
);
```

Notes:

- Subtask names are unique **per project** (`UNIQUE(project_id, name)`), not
  globally — `ProjectA/Design` and `ProjectB/Design` can coexist.
- "The timer is running" means there exists a `time_entries` row with
  `ended_at IS NULL`. At most one such row may exist at a time, enforced in
  application logic (any `start` closes the existing open row first).
- Elapsed/duration is always computed on demand (`ended_at` or `now()` minus
  `started_at`) — nothing runs in the background, so closing the shell,
  logging out, or rebooting has no effect on a running timer. The next
  `tt status` simply reads the still-open row and computes elapsed time from
  its `started_at`.

## Commands & behavior

- **`tt start <project> <subtask>`** — looks up project/subtask by name. If
  either doesn't exist, prompts `Project 'X' doesn't exist. Create it? [y/N]`
  (same wording pattern for subtask). Confirm creates it and proceeds;
  decline aborts with no changes made. If a timer is already running, it is
  closed (`ended_at = now`) automatically before the new one opens — this is
  silent, not prompted, since superseding the running timer is the whole
  point of `start`.
- **`tt stop [--at TIME]`** — closes the running entry (`ended_at = now`, or
  the given `--at` time to backdate it). If no timer is running, prints
  "No timer running" and exits cleanly (not an error).
- **`tt status`** — if a timer is running, shows project/subtask and elapsed
  time. Otherwise prints "No timer running."
- **`tt list`** — lists past time entries, most recent first: entry ID,
  project/subtask, start, end, duration. No filtering/date-range (that's
  reporting, deferred).
- **`tt edit <entry_id> [--start TIME] [--end TIME]`** — updates either
  timestamp on an existing entry (running or finished). At least one of
  `--start`/`--end` is required. Rejects the edit with a clear error (no
  partial write) if the resulting `start >= end`.

### Time input format

`--at`, `--start`, `--end` accept either:

- `HH:MM` — interpreted as today's date
- `YYYY-MM-DD HH:MM` — explicit date, for correcting entries from a previous
  day

An unparseable value produces a clear error and no change is made.

## Error handling

- Invalid/unparseable time input → clear error, no partial write.
- Edit resulting in `start >= end` → rejected, clear error, no partial write.
- `stop`/`status` with nothing running → informational message, exit code 0
  (not treated as an error).
- Declining an auto-create confirmation → abort the command with no DB
  changes.

## Testing

pytest, with each test pointing at a temporary SQLite file (`tmp_path`
fixture) instead of the real `~/.timetracker/timetracker.db`, so tests never
touch real data. Cover at minimum:

- Starting a new timer closes any currently-running timer (single-timer
  enforcement).
- Auto-create confirmation prompts for missing project/subtask (both accept
  and decline paths).
- `edit` validation rejects `start >= end`.
- Time-format parsing for both `HH:MM` and full-datetime forms, including
  the unparseable-input error path.
- Subtask names can repeat across different projects but not within the same
  project.

## Out of scope (deferred)

- Reports/summaries (e.g. hours per project over a date range)
- Shell tab-completion for project/subtask names
- Deleting entries
- GUI
