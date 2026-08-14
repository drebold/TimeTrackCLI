# Time Tracker App

A time-stamping app for tracking work.

## Update suggestions
- Nicer UI with richclick
- Auto completion for projects.
- A way to customize the output from week --table --copy, for different finance reporting apps. (non-priority)
- Edit subtask
- Flag overlap, rather then refuse it. Offer to edit end time of overlapped session?

## Core concept

- Work is organized into **projects**, each with **subtasks**.
- There is a single timer for the whole app, not one per project or subtask.
- Starting the timer requires attaching it to one subtask (under a project).
- Only one timer can run at a time — starting a new timer stops/finishes whatever is currently running.

## Tech stack

- Python + [Typer](https://typer.tiangolo.com/) for the CLI, stdlib `sqlite3` for storage, no ORM.
- Package layout: `src/time_tracker_app/` (`db.py` schema/queries, `cli.py` commands, `models.py` dataclasses, `timeparse.py`), tests in `tests/` (pytest).
- **`uv` is blocked by this machine's IT policy (Heimdal).** Use plain `venv` + `pip`: `.\.venv\Scripts\python.exe -m pytest`, `.\.venv\Scripts\python.exe -m pip install -e . pytest`. Don't reach for `uv` commands.
- The installed `tt.exe` console-script launcher is also blocked (unsigned generated exe). Run via `python -m time_tracker_app` instead, or use the `tt.cmd` wrapper at `C:\Users\dre\.local\bin\tt.cmd` (already on PATH) which shells out to the project's `.venv` python — that's what `tt <command>` resolves to in a real terminal.
- See `docs/superpowers/specs/` and `docs/superpowers/plans/` for the original design/plan docs (historical — many features have been added since without updating them; the code and tests are the source of truth for current behavior).

## Working in this repo

- When adding features, keep the "one active timer at a time" rule central to the data model and UI — it shouldn't be possible to have two running timers simultaneously, even across different projects.
- **The real database is live, in-use data feeding the user's actual finance app** (`~/.timetracker/timetracker.db`, i.e. `C:\Users\dre\.timetracker\timetracker.db`). Tests and manual smoke-testing must always point `TT_DB_PATH` at a throwaway file, set in the *same* shell command as the `tt`/`python -m time_tracker_app` invocation — a debug script that omitted it once accidentally interrupted the user's real running timer and wrote bogus data into the real DB. Double-check `TT_DB_PATH` is set before any ad-hoc/manual command that isn't going through the pytest suite.
- Schema changes to existing tables must be additive, backward-compatible migrations (`_migrate_*_columns` functions in `db.py`, guarded by `PRAGMA table_info` checks) — never assume a fresh database.
