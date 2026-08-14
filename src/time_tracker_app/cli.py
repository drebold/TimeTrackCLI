import os
import subprocess
import tempfile
from datetime import date, datetime, timedelta

import typer

from time_tracker_app import db
from time_tracker_app.timeparse import TimeParseError, parse_time_input

app = typer.Typer()

project_app = typer.Typer()
app.add_typer(project_app, name="project", help="Manage project metadata")

subtask_app = typer.Typer()
app.add_typer(subtask_app, name="subtask", help="Manage subtask metadata")

DANISH_WEEKDAYS = ["Man", "Tir", "Ons", "Tor", "Fre", "Lør", "Søn"]


@project_app.command("list")
def project_list(
    project: str = typer.Argument(None, help="Show this project's Sagsnr. and subtasks"),
) -> None:
    """List all projects, or show one project's Sagsnr. and subtasks."""
    conn = db.get_connection(db.get_db_path())
    if project is not None:
        proj = db.get_project_by_name(conn, project)
        if proj is None:
            typer.echo(f"No project named '{project}'")
            raise typer.Exit(code=1)
        typer.echo(f"{proj.name}  Sagsnr.: {proj.case_number or '(none)'}")
        subtasks = db.list_subtasks(conn, proj.id)
        if not subtasks:
            typer.echo("  (no subtasks)")
            return
        for sub in subtasks:
            typer.echo(
                f"  {sub.name}  Sagsopgave: {sub.case_task or '(none)'}  "
                f"Arbejdstype: {sub.work_type or '(none)'}"
            )
        return
    projects = db.list_projects(conn)
    if not projects:
        typer.echo("No projects yet")
        return
    for proj in projects:
        typer.echo(f"{proj.name}  Sagsnr.: {proj.case_number or '(none)'}")


def _get_or_create_project(conn, name: str) -> db.Project | None:
    project = db.get_project_by_name(conn, name)
    if project is not None:
        return project
    if not typer.confirm(f"Project '{name}' doesn't exist. Create it?"):
        return None
    # typer.prompt with no `default` already re-prompts silently on blank
    # input, so this is guaranteed non-empty by the time it returns.
    case_number = typer.prompt("Sagsnr. (case number)")
    return db.create_project(conn, name, case_number=case_number)


def _get_or_create_subtask(conn, project_id: int, project_name: str, name: str) -> db.Subtask | None:
    subtask = db.get_subtask_by_name(conn, project_id, name)
    if subtask is not None:
        return subtask
    if not typer.confirm(f"Subtask '{name}' doesn't exist under '{project_name}'. Create it?"):
        return None
    case_task = typer.prompt("Sagsopgave (task no., optional)", default="", show_default=False)
    work_type = typer.prompt("Arbejdstype (work-type code, optional)", default="", show_default=False)
    return db.create_subtask(
        conn,
        project_id,
        name,
        case_task=case_task or None,
        work_type=work_type or None,
    )


def _resolve_overlap(
    conn, error: db.OverlapError, subject_entry_id: int | None = None
) -> tuple[datetime, datetime | None] | None:
    """Interactively resolve an overlap raised by start/stop/add/edit.

    Returns the (start, end) to retry the original action with, or None if the
    user cancelled. Trimming the conflicting entry returns the ORIGINAL
    requested (start, end) unchanged, since the conflict should be gone on
    retry; clipping returns an ADJUSTED (start, end) with the conflict left
    untouched.

    `subject_entry_id` is the id of the entry already in the table that this
    action concerns (the running entry being stopped, or the entry being
    edited) - it still holds its old, not-yet-updated values at this point, so
    trimming the conflict must also exclude it from the overlap re-check or it
    can spuriously conflict with itself. None for start/add, which don't have
    an existing row yet.
    """
    conflict = error.conflict
    requested_start = error.requested_start
    requested_end = error.requested_end
    conflict_start = db.parse_dt(conflict.started_at)
    conflict_end = db.parse_dt(conflict.ended_at) if conflict.ended_at is not None else datetime.now()

    typer.echo(
        f"Overlaps entry {conflict.id} ({conflict.started_at} -> {conflict.ended_at or 'running'})"
    )

    nested = (
        requested_end is not None
        and conflict_start <= requested_start
        and requested_end <= conflict_end
    )
    swallow = (
        requested_end is not None
        and requested_start <= conflict_start
        and requested_end >= conflict_end
    )
    new_starts_inside_conflict = conflict_start <= requested_start < conflict_end

    trim_kwargs: dict[str, datetime] | None = None
    clip_start, clip_end = requested_start, requested_end
    options: dict[str, str] = {}

    if nested:
        typer.echo(
            f"Your requested time falls entirely inside entry {conflict.id} - there's no way to "
            f"trim or clip around it. Edit or delete entry {conflict.id} first if you want to replace it."
        )
    elif swallow:
        typer.echo(
            f"Your requested time fully covers entry {conflict.id} - trimming isn't possible "
            f"without invalidating it. Use `tt delete {conflict.id}` first if you want to replace it."
        )
        clip_end = conflict_start
        options["2"] = f"End your entry at {db.format_dt(conflict_start)} instead"
    elif new_starts_inside_conflict:
        trim_kwargs = {"end": requested_start}
        clip_start = conflict_end
        options["1"] = f"Trim entry {conflict.id} to end at {db.format_dt(requested_start)}"
        options["2"] = f"Start your entry at {db.format_dt(conflict_end)} instead"
    else:
        trim_kwargs = {"start": requested_end}
        clip_end = conflict_start
        options["1"] = f"Trim entry {conflict.id} to start at {db.format_dt(requested_end)}"
        options["2"] = f"End your entry at {db.format_dt(conflict_start)} instead"

    options["3"] = "Cancel"
    for key, desc in options.items():
        typer.echo(f"  [{key}] {desc}")
    choice = typer.prompt("Choice", default="3")

    if choice == "1" and trim_kwargs is not None:
        try:
            db.update_entry(
                conn, conflict.id, extra_exclude_entry_id=subject_entry_id, **trim_kwargs
            )
        except (db.EditError, db.OverlapError) as e:
            typer.echo(f"Error trimming entry {conflict.id}: {e}")
            return None
        return requested_start, requested_end
    if choice == "2" and "2" in options:
        return clip_start, clip_end
    return None


def _print_entries(entries: list[db.TimeEntryView]) -> None:
    if not entries:
        typer.echo("No entries yet")
        return
    for entry in entries:
        end = entry.ended_at if entry.ended_at is not None else "running"
        typer.echo(f"[{entry.id}] {entry.project_name}/{entry.subtask_name}  {entry.started_at} -> {end}")


def _resolve_week_range(week_arg: str | None, today: date) -> tuple[date, date]:
    this_monday = today - timedelta(days=today.weekday())
    if week_arg is None:
        monday = this_monday
    elif week_arg == "last":
        monday = this_monday - timedelta(days=7)
    else:
        try:
            week_number = int(week_arg)
        except ValueError:
            raise ValueError(f"invalid week {week_arg!r} (expected a week number or 'last')") from None
        monday = date.fromisocalendar(today.isocalendar()[0], week_number, 1)
    sunday = monday + timedelta(days=6)
    return monday, sunday


def _format_hours(value: float) -> str:
    if not value:
        return ""
    text = f"{value:.2f}".rstrip("0").rstrip(".")
    return text.replace(".", ",")


def _day_header(d: date) -> str:
    return f"{d.day} {DANISH_WEEKDAYS[d.weekday()]}"


def _week_table_lines(conn, monday: date, sunday: date) -> list[str]:
    report = db.get_week_report(conn, monday, sunday)
    days = [monday + timedelta(days=i) for i in range(7)]
    header = ["Type", "Sagsnr.", "Sagsopgave", "Arbejdstype", "Beskrivelse"] + [
        _day_header(d) for d in days
    ]
    lines = ["\t".join(header)]
    for row in report:
        cells = [
            "Sag",
            row.sagsnr or "",
            row.sagsopgave or "",
            row.arbejdstype or "",
            row.beskrivelse,
        ] + [_format_hours(h) for h in row.hours_by_day]
        lines.append("\t".join(cells))
    return lines


def _copy_to_clipboard(text: str) -> None:
    """Copy `text` to the Windows clipboard via PowerShell's Set-Clipboard.

    Terminals render tab characters as visual spaces on copy, so copying
    tab-separated CLI output straight from the terminal loses the real tabs
    Excel needs to split into columns. Routing through the clipboard directly
    sidesteps that. A temp file (not stdin) carries the text so encoding is
    unambiguous - the day headers and Beskrivelse/Sagsnr. values can contain
    Danish characters (e.g. "Lør", "Søn").
    """
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False, encoding="utf-8", newline=""
    ) as f:
        f.write(text)
        temp_path = f.name
    try:
        escaped_path = temp_path.replace("'", "''")
        subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                f"Set-Clipboard -Value (Get-Content -Raw -Encoding UTF8 -LiteralPath '{escaped_path}')",
            ],
            check=True,
            capture_output=True,
        )
    finally:
        os.unlink(temp_path)


@app.command()
def start(
    project: str,
    subtask: str,
    at: str = typer.Option(None, "--at", help="Backdate the start time, e.g. '09:00'"),
) -> None:
    """Start the timer on a subtask, creating project/subtask if confirmed."""
    conn = db.get_connection(db.get_db_path())
    now = datetime.now()
    if at is not None:
        try:
            start_time = parse_time_input(at, now)
        except TimeParseError as e:
            typer.echo(f"Error: {e}")
            raise typer.Exit(code=1)
    else:
        start_time = now

    proj = _get_or_create_project(conn, project)
    if proj is None:
        typer.echo("Aborted: project not created.")
        raise typer.Exit(code=1)
    sub = _get_or_create_subtask(conn, proj.id, proj.name, subtask)
    if sub is None:
        typer.echo("Aborted: subtask not created.")
        raise typer.Exit(code=1)

    while True:
        try:
            db.start_timer(conn, sub.id, start_time)
            break
        except db.OverlapError as e:
            resolved = _resolve_overlap(conn, e)
            if resolved is None:
                typer.echo("Aborted")
                raise typer.Exit(code=1)
            start_time, _ = resolved
    typer.echo(f"Started timer on {proj.name}/{sub.name}")


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
    running = db.get_running_entry(conn)
    while True:
        try:
            entry = db.stop_timer(conn, stop_time)
            break
        except db.OverlapError as e:
            resolved = _resolve_overlap(conn, e, subject_entry_id=running.id if running else None)
            if resolved is None:
                typer.echo("Aborted")
                raise typer.Exit(code=1)
            _, stop_time = resolved
    if entry is None:
        typer.echo("No timer running")
        return
    typer.echo(f"Stopped timer (entry {entry.id})")


@app.command()
def add(
    project: str,
    subtask: str,
    start: str = typer.Option(..., "--start", help="Start time, e.g. '09:00'"),
    end: str = typer.Option(..., "--end", help="End time, e.g. '17:00'"),
    entry_date: str = typer.Option(
        None, "--date", help="Date for the entry, YYYY-MM-DD (default: today)"
    ),
) -> None:
    """Add a complete time entry directly, without starting/stopping a timer."""
    if entry_date is not None:
        try:
            day = datetime.strptime(entry_date, "%Y-%m-%d").date()
        except ValueError:
            typer.echo(f"Error: invalid date {entry_date!r} (expected YYYY-MM-DD)")
            raise typer.Exit(code=1)
    else:
        day = datetime.now().date()

    now = datetime.now()
    try:
        start_time = parse_time_input(start, now)
        end_time = parse_time_input(end, now)
    except TimeParseError as e:
        typer.echo(f"Error: {e}")
        raise typer.Exit(code=1)

    if entry_date is not None:
        start_time = start_time.replace(year=day.year, month=day.month, day=day.day)
        end_time = end_time.replace(year=day.year, month=day.month, day=day.day)

    conn = db.get_connection(db.get_db_path())
    proj = _get_or_create_project(conn, project)
    if proj is None:
        typer.echo("Aborted: project not created.")
        raise typer.Exit(code=1)
    sub = _get_or_create_subtask(conn, proj.id, proj.name, subtask)
    if sub is None:
        typer.echo("Aborted: subtask not created.")
        raise typer.Exit(code=1)

    while True:
        try:
            entry = db.add_entry(conn, sub.id, start_time, end_time)
            break
        except db.EditError as e:
            typer.echo(f"Error: {e}")
            raise typer.Exit(code=1)
        except db.OverlapError as e:
            resolved = _resolve_overlap(conn, e)
            if resolved is None:
                typer.echo("Aborted")
                raise typer.Exit(code=1)
            start_time, end_time = resolved

    typer.echo(f"Added entry {entry.id} on {proj.name}/{sub.name} ({entry.started_at} -> {entry.ended_at})")


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


@app.command(name="list")
def list_entries_cmd() -> None:
    """List past and current time entries, most recent first."""
    conn = db.get_connection(db.get_db_path())
    _print_entries(db.list_entries(conn))


@app.command()
def today() -> None:
    """List today's time entries."""
    conn = db.get_connection(db.get_db_path())
    today_date = datetime.now().date()
    _print_entries(db.list_entries(conn, start_date=today_date, end_date=today_date))


@app.command()
def week(
    week_arg: str = typer.Argument(None, metavar="[WEEK]", help="ISO week number or 'last' (default: current week)"),
    table: bool = typer.Option(
        False, "--table", help="Print as a tab-separated table for pasting into the finance app"
    ),
    copy: bool = typer.Option(
        False, "--copy", "-c", help="Also copy the table to the clipboard (requires --table)"
    ),
) -> None:
    """List this week's (or a given week's) time entries."""
    if copy and not table:
        typer.echo("Error: --copy requires --table")
        raise typer.Exit(code=1)

    conn = db.get_connection(db.get_db_path())
    today_date = datetime.now().date()
    try:
        monday, sunday = _resolve_week_range(week_arg, today_date)
    except ValueError as e:
        typer.echo(f"Error: {e}")
        raise typer.Exit(code=1)

    if table:
        lines = _week_table_lines(conn, monday, sunday)
        for line in lines:
            typer.echo(line)
        if copy:
            try:
                _copy_to_clipboard("\n".join(lines[1:]))
                typer.echo("(copied to clipboard, header excluded)")
            except Exception as e:
                typer.echo(f"Warning: could not copy to clipboard ({e})")
        return
    _print_entries(db.list_entries(conn, start_date=monday, end_date=sunday))


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

    while True:
        try:
            updated = db.update_entry(conn, entry_id, start=start_dt, end=end_dt)
            break
        except db.EditError as e:
            typer.echo(f"Error: {e}")
            raise typer.Exit(code=1)
        except db.OverlapError as e:
            resolved = _resolve_overlap(conn, e, subject_entry_id=entry_id)
            if resolved is None:
                typer.echo("Aborted")
                raise typer.Exit(code=1)
            start_dt, end_dt = resolved

    typer.echo(f"Updated entry {updated.id}")


@app.command()
def delete(
    entry_id: int,
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip the confirmation prompt"),
) -> None:
    """Delete a time entry."""
    conn = db.get_connection(db.get_db_path())
    entry = db.get_entry(conn, entry_id)
    if entry is None:
        typer.echo(f"No entry with id {entry_id}")
        raise typer.Exit(code=1)

    project_name, subtask_name = db.get_subtask_project_names(conn, entry.subtask_id)
    end = entry.ended_at if entry.ended_at is not None else "running"
    if not yes and not typer.confirm(
        f"Delete entry {entry.id} ({project_name}/{subtask_name}  {entry.started_at} -> {end})?"
    ):
        typer.echo("Aborted")
        raise typer.Exit(code=1)

    db.delete_entry(conn, entry_id)
    typer.echo(f"Deleted entry {entry_id}")


@project_app.command("edit")
def project_edit(
    project: str,
    case_number: str = typer.Option(None, "--case-number", help="Set the Sagsnr. (case number)"),
    name: str = typer.Option(None, "--name", help="Rename the project"),
) -> None:
    """Edit an existing project's Sagsnr. and/or name."""
    if case_number is None and name is None:
        typer.echo("Error: provide --case-number and/or --name")
        raise typer.Exit(code=1)

    conn = db.get_connection(db.get_db_path())
    proj = db.get_project_by_name(conn, project)
    if proj is None:
        typer.echo(f"No project named '{project}'")
        raise typer.Exit(code=1)

    try:
        updated = db.update_project(conn, proj.id, name=name, case_number=case_number)
    except db.EditError as e:
        typer.echo(f"Error: {e}")
        raise typer.Exit(code=1)

    typer.echo(f"Updated project '{updated.name}' (Sagsnr.: {updated.case_number or '(none)'})")


@project_app.command("create")
def project_create(
    name: str,
    case_number: str = typer.Option(..., "--case-number", help="Sagsnr. (case number)"),
) -> None:
    """Create a new project."""
    conn = db.get_connection(db.get_db_path())
    if db.get_project_by_name(conn, name) is not None:
        typer.echo(f"Error: project '{name}' already exists")
        raise typer.Exit(code=1)
    project = db.create_project(conn, name, case_number=case_number)
    typer.echo(f"Created project '{project.name}' (Sagsnr.: {project.case_number})")


@project_app.command("delete")
def project_delete(
    name: str,
    force: bool = typer.Option(False, "--force", help="Also delete its subtasks and their time entries"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip the confirmation prompt"),
) -> None:
    """Delete a project."""
    conn = db.get_connection(db.get_db_path())
    proj = db.get_project_by_name(conn, name)
    if proj is None:
        typer.echo(f"No project named '{name}'")
        raise typer.Exit(code=1)

    subtask_count = db.get_project_subtask_count(conn, proj.id)
    entry_count = db.get_project_entry_count(conn, proj.id)

    if subtask_count > 0 and not force:
        typer.echo(
            f"Error: project '{name}' has {subtask_count} subtask(s) and {entry_count} "
            f"time entries. Use --force to delete them all."
        )
        raise typer.Exit(code=1)

    prompt = (
        f"Delete project '{name}', its {subtask_count} subtask(s), and {entry_count} time entries?"
        if subtask_count > 0
        else f"Delete project '{name}'?"
    )
    if not yes and not typer.confirm(prompt):
        typer.echo("Aborted")
        raise typer.Exit(code=1)

    db.delete_project(conn, proj.id, force=force)
    typer.echo(f"Deleted project '{name}'")


@subtask_app.command("edit")
def subtask_edit(
    project: str,
    subtask: str,
    case_task: str = typer.Option(None, "--case-task", help="Set the Sagsopgave (task no.)"),
    work_type: str = typer.Option(None, "--work-type", help="Set the Arbejdstype (work-type code)"),
    name: str = typer.Option(None, "--name", help="Rename the subtask"),
) -> None:
    """Edit an existing subtask's Sagsopgave, Arbejdstype, and/or name."""
    if case_task is None and work_type is None and name is None:
        typer.echo("Error: provide --case-task, --work-type, and/or --name")
        raise typer.Exit(code=1)

    conn = db.get_connection(db.get_db_path())
    proj = db.get_project_by_name(conn, project)
    if proj is None:
        typer.echo(f"No project named '{project}'")
        raise typer.Exit(code=1)
    sub = db.get_subtask_by_name(conn, proj.id, subtask)
    if sub is None:
        typer.echo(f"No subtask named '{subtask}' under '{project}'")
        raise typer.Exit(code=1)

    try:
        updated = db.update_subtask(conn, sub.id, name=name, case_task=case_task, work_type=work_type)
    except db.EditError as e:
        typer.echo(f"Error: {e}")
        raise typer.Exit(code=1)

    typer.echo(
        f"Updated subtask '{updated.name}' (Sagsopgave: {updated.case_task or '(none)'}, "
        f"Arbejdstype: {updated.work_type or '(none)'})"
    )
