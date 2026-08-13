from datetime import date, datetime, timedelta

import typer

from time_tracker_app import db
from time_tracker_app.timeparse import TimeParseError, parse_time_input

app = typer.Typer()

DANISH_WEEKDAYS = ["Man", "Tir", "Ons", "Tor", "Fre", "Lør", "Søn"]


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
    case_task = typer.prompt("Sagsopgave (task no., optional)", default="", show_default=False)
    work_type = typer.prompt("Arbejdstype (work-type code, optional)", default="", show_default=False)
    return db.create_subtask(
        conn,
        project_id,
        name,
        case_task=case_task or None,
        work_type=work_type or None,
    )


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


def _print_week_table(conn, monday: date, sunday: date) -> None:
    report = db.get_week_report(conn, monday, sunday)
    days = [monday + timedelta(days=i) for i in range(7)]
    header = ["Type", "Sagsnr.", "Sagsopgave", "Arbejdstype", "Beskrivelse"] + [
        _day_header(d) for d in days
    ]
    typer.echo("\t".join(header))
    for row in report:
        cells = [
            "Sag",
            row.sagsnr,
            row.sagsopgave or "",
            row.arbejdstype or "",
            row.beskrivelse,
        ] + [_format_hours(h) for h in row.hours_by_day]
        typer.echo("\t".join(cells))


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

    try:
        db.start_timer(conn, sub.id, start_time)
    except db.OverlapError as e:
        typer.echo(f"Error: {e}")
        raise typer.Exit(code=1)
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
    try:
        entry = db.stop_timer(conn, stop_time)
    except db.OverlapError as e:
        typer.echo(f"Error: {e}")
        raise typer.Exit(code=1)
    if entry is None:
        typer.echo("No timer running")
        return
    typer.echo(f"Stopped timer (entry {entry.id})")


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
) -> None:
    """List this week's (or a given week's) time entries."""
    conn = db.get_connection(db.get_db_path())
    today_date = datetime.now().date()
    try:
        monday, sunday = _resolve_week_range(week_arg, today_date)
    except ValueError as e:
        typer.echo(f"Error: {e}")
        raise typer.Exit(code=1)

    if table:
        _print_week_table(conn, monday, sunday)
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

    try:
        updated = db.update_entry(conn, entry_id, start=start_dt, end=end_dt)
    except (db.EditError, db.OverlapError) as e:
        typer.echo(f"Error: {e}")
        raise typer.Exit(code=1)

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
