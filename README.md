# tt — Time Tracker

A CLI time tracker: work is organized into **projects**, each with **subtasks**.
There's a single timer for the whole app — starting a new timer always stops
whatever's currently running.

## Setup

`uv` is not available on this machine, so use a plain `venv`:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e . pytest
```

The `tt` command is available globally via `C:\Users\dre\.local\bin\tt.cmd`,
which wraps this project's `.venv` python. If that's ever missing or pointing
at the wrong `.venv`, run commands directly instead:

```powershell
.\.venv\Scripts\python.exe -m time_tracker_app <command>
```

Data lives in `~/.timetracker/timetracker.db`, independent of this project
folder. Override the location with the `TT_DB_PATH` environment variable
(used for tests and manual testing so real data is never touched).

## Interactive UI

```powershell
tt tui
```

A [Textual](https://textual.textualize.io/) terminal UI covering everything
the CLI does, across three tabs:

- **Timer** — live running-timer status, start/stop, an "Add entry..." dialog
  for backdated entries, and a list of entries (Today/This week/All) you can
  edit (`e`) or delete (`d`).
- **Projects** — project list next to the selected project's subtasks; create,
  rename, and delete projects (cascade-deletes subtasks/entries with
  confirmation), and rename subtasks.
- **Week** — the same finance-report table as `week --table`, with Prev/Next
  week navigation and a "Copy to clipboard" button.

Starting a timer or adding an entry lets you create a new project/subtask
inline instead of picking an existing one, same as the CLI's prompts.
Keybindings: `a` add entry, `d` delete selected, `e` edit selected, `r`
refresh, `q` quit.

## Commands

**Timer**
| Command | What it does |
|---|---|
| `tt start <project> <subtask> [--at TIME]` | Start the timer, closing any currently-running one. Prompts to create the project/subtask if they don't exist yet (project creation asks for Sagsnr.; subtask creation asks for Sagsopgave/Arbejdstype, both optional). `--at` backdates the start. |
| `tt stop [--at TIME]` | Stop the running timer. No-op (not an error) if nothing's running. |
| `tt status` | Show the currently running timer and elapsed time. |
| `tt add <project> <subtask> --start TIME --end TIME [--date DATE]` | Add a complete entry directly, without starting/stopping a timer. `--date` defaults to today (`YYYY-MM-DD`). Doesn't touch a running timer. |
| `tt tui` | Launch the interactive terminal UI (see [Interactive UI](#interactive-ui) above). |

**Viewing entries**
| Command | What it does |
|---|---|
| `tt list` | All entries, most recent first. |
| `tt today` | Today's entries. |
| `tt week [WEEK\|last]` | This week's entries (or a given ISO week number, or `last`). |
| `tt week --table` | Finance-report format: one row per subtask, hours by day, tab-separated. |
| `tt week --table --copy` | Same, plus copies it to the clipboard (header excluded) for pasting into Excel — plain terminal copy loses the tab characters, this doesn't. |

**Editing/deleting entries**
| Command | What it does |
|---|---|
| `tt edit <entry_id> [--start TIME] [--end TIME]` | Fix an entry's time(s). Entry IDs come from `tt list`/`tt today`/`tt week`. |
| `tt delete <entry_id> [--yes]` | Delete an entry. Confirms first unless `--yes`. |

**Projects**
| Command | What it does |
|---|---|
| `tt project create <name> --case-number VALUE` | Create a project explicitly (Sagsnr. required). |
| `tt project list` | List all projects with their Sagsnr. |
| `tt project list <name>` | Show one project's Sagsnr. and its subtasks. |
| `tt project edit <name> [--case-number VALUE] [--name VALUE]` | Update a project's Sagsnr. and/or rename it. |
| `tt project delete <name> [--force] [--yes]` | Delete a project. Blocks if it has subtasks — `--force` cascades (deletes subtasks and their entries too). |

Subtasks have no CRUD of their own — `start`/`add` are the only way to create
them, and `tt project list <name>` is the only way to view them.

Times accept `HH:MM` (today) or `YYYY-MM-DD HH:MM` (explicit date). Entries
are validated so they never overlap another entry on the same day.

## Testing

```powershell
.\.venv\Scripts\python.exe -m pytest -v
```
