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


def test_status_shows_running_timer(cli_env):
    runner.invoke(app, ["start", "ProjectX", "Task1"], input="y\ny\n")

    result = runner.invoke(app, ["status"])

    assert result.exit_code == 0
    assert "ProjectX/Task1" in result.output


def test_status_shows_no_timer_running(cli_env):
    result = runner.invoke(app, ["status"])

    assert result.exit_code == 0
    assert "No timer running" in result.output


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
