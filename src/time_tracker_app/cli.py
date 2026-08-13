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
    entries = db.list_entries(conn)
    if not entries:
        typer.echo("No entries yet")
        return
    for entry in entries:
        end = entry.ended_at if entry.ended_at is not None else "running"
        typer.echo(f"[{entry.id}] {entry.project_name}/{entry.subtask_name}  {entry.started_at} -> {end}")


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
    except db.EditError as e:
        typer.echo(f"Error: {e}")
        raise typer.Exit(code=1)

    typer.echo(f"Updated entry {updated.id}")
