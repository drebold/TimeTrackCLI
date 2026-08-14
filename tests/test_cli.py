from datetime import datetime, timedelta

from typer.testing import CliRunner

from time_tracker_app.cli import app
from time_tracker_app import db

runner = CliRunner()


def test_start_creates_project_and_subtask_when_confirmed(cli_env):
    result = runner.invoke(app, ["start", "ProjectX", "Task1"], input="y\n2606-151\ny\n\n\n")

    assert result.exit_code == 0
    assert "Started timer on ProjectX/Task1" in result.output

    conn = db.get_connection(cli_env)
    running = db.get_running_entry(conn)
    assert running is not None


def test_start_prompts_for_required_sagsnr_when_creating_project(cli_env):
    result = runner.invoke(app, ["start", "PLC Work", "Task1"], input="y\n2606-151\ny\n\n\n")

    assert result.exit_code == 0
    conn = db.get_connection(cli_env)
    project = db.get_project_by_name(conn, "PLC Work")
    assert project.case_number == "2606-151"


def test_start_reprompts_when_sagsnr_left_blank(cli_env):
    # typer.prompt with no default re-prompts silently on blank input, so a
    # blank first answer is skipped rather than accepted as an empty Sagsnr.
    result = runner.invoke(app, ["start", "PLC Work", "Task1"], input="y\n\n2606-151\ny\n\n\n")

    assert result.exit_code == 0
    conn = db.get_connection(cli_env)
    project = db.get_project_by_name(conn, "PLC Work")
    assert project.case_number == "2606-151"


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
    runner.invoke(app, ["start", "ProjectX", "Task1"], input="y\n2606-151\ny\n\n\n")

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
    runner.invoke(app, ["start", "ProjectX", "Task1"], input="y\n2606-151\ny\n\n\n")

    result = runner.invoke(app, ["stop", "--at", "08:00"])

    assert result.exit_code == 0
    conn = db.get_connection(cli_env)
    entries = db.list_entries(conn)
    assert entries[0].ended_at.endswith("08:00:00")


def test_stop_with_unparseable_at_is_an_error(cli_env):
    runner.invoke(app, ["start", "ProjectX", "Task1"], input="y\n2606-151\ny\n\n\n")

    result = runner.invoke(app, ["stop", "--at", "not-a-time"])

    assert result.exit_code == 1
    conn = db.get_connection(cli_env)
    assert db.get_running_entry(conn) is not None


def test_add_creates_entry_for_today_by_default(cli_env):
    result = runner.invoke(
        app,
        ["add", "ProjectX", "Task1", "--start", "09:00", "--end", "12:30"],
        input="y\n2606-151\ny\n\n\n",
    )

    assert result.exit_code == 0
    assert "Added entry" in result.output
    conn = db.get_connection(cli_env)
    entries = db.list_entries(conn)
    assert len(entries) == 1
    today = datetime.now().date().isoformat()
    assert entries[0].started_at.startswith(f"{today}T09:00:00")
    assert entries[0].ended_at.startswith(f"{today}T12:30:00")


def test_add_with_date_creates_entry_for_given_day(cli_env):
    result = runner.invoke(
        app,
        [
            "add", "ProjectX", "Task1",
            "--start", "09:00", "--end", "12:30", "--date", "2026-08-10",
        ],
        input="y\n2606-151\ny\n\n\n",
    )

    assert result.exit_code == 0
    conn = db.get_connection(cli_env)
    entries = db.list_entries(conn)
    assert entries[0].started_at == "2026-08-10T09:00:00"
    assert entries[0].ended_at == "2026-08-10T12:30:00"


def test_add_does_not_prompt_for_existing_project_and_subtask(cli_env):
    conn = db.get_connection(cli_env)
    project = db.create_project(conn, "ProjectX", case_number="2606-151")
    db.create_subtask(conn, project.id, "Task1")

    result = runner.invoke(app, ["add", "ProjectX", "Task1", "--start", "09:00", "--end", "12:30"])

    assert result.exit_code == 0
    conn = db.get_connection(cli_env)
    assert len(db.list_entries(conn)) == 1


def test_add_rejects_start_after_end(cli_env):
    conn = db.get_connection(cli_env)
    project = db.create_project(conn, "ProjectX", case_number="2606-151")
    db.create_subtask(conn, project.id, "Task1")

    result = runner.invoke(app, ["add", "ProjectX", "Task1", "--start", "12:30", "--end", "09:00"])

    assert result.exit_code == 1
    assert "start must be before end" in result.output


def test_add_rejects_overlap_with_existing_entry(cli_env):
    conn = db.get_connection(cli_env)
    project = db.create_project(conn, "ProjectX", case_number="2606-151")
    subtask = db.create_subtask(conn, project.id, "Task1")
    db.add_entry(conn, subtask.id, datetime(2026, 8, 10, 9, 0, 0), datetime(2026, 8, 10, 12, 0, 0))

    result = runner.invoke(
        app,
        [
            "add", "ProjectX", "Task1",
            "--start", "11:00", "--end", "13:00", "--date", "2026-08-10",
        ],
        input="3\n",
    )

    assert result.exit_code == 1
    assert "Overlaps entry" in result.output
    assert "Aborted" in result.output


def test_add_invalid_date_is_an_error(cli_env):
    conn = db.get_connection(cli_env)
    project = db.create_project(conn, "ProjectX", case_number="2606-151")
    db.create_subtask(conn, project.id, "Task1")

    result = runner.invoke(
        app,
        ["add", "ProjectX", "Task1", "--start", "09:00", "--end", "12:00", "--date", "not-a-date"],
    )

    assert result.exit_code == 1
    assert "invalid date" in result.output


def test_add_does_not_disturb_running_timer(cli_env):
    conn = db.get_connection(cli_env)
    project = db.create_project(conn, "ProjectX", case_number="2606-151")
    subtask = db.create_subtask(conn, project.id, "Task1")
    running = db.start_timer(conn, subtask.id, datetime(2026, 8, 13, 9, 0, 0))

    result = runner.invoke(
        app,
        [
            "add", "ProjectX", "Task1",
            "--start", "09:00", "--end", "10:00", "--date", "2026-08-01",
        ],
    )

    assert result.exit_code == 0
    conn = db.get_connection(cli_env)
    assert db.get_running_entry(conn).id == running.id


def test_status_shows_running_timer(cli_env):
    runner.invoke(app, ["start", "ProjectX", "Task1"], input="y\n2606-151\ny\n\n\n")

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
    runner.invoke(app, ["start", "ProjectX", "Task1"], input="y\n2606-151\ny\n\n\n")
    runner.invoke(app, ["stop"])
    runner.invoke(app, ["start", "ProjectX", "Task2"], input="y\n\n\n")

    result = runner.invoke(app, ["list"])

    assert result.exit_code == 0
    lines = [line for line in result.output.splitlines() if "ProjectX" in line]
    assert len(lines) == 2
    assert "Task2" in lines[0]
    assert "Task1" in lines[1]
    assert "running" in lines[0]


def test_edit_updates_end_time(cli_env):
    runner.invoke(app, ["start", "ProjectX", "Task1"], input="y\n2606-151\ny\n\n\n")
    runner.invoke(app, ["stop"])
    conn = db.get_connection(cli_env)
    entry_id = db.list_entries(conn)[0].id

    result = runner.invoke(app, ["edit", str(entry_id), "--end", "17:00"])

    assert result.exit_code == 0
    assert f"Updated entry {entry_id}" in result.output
    conn = db.get_connection(cli_env)
    assert db.list_entries(conn)[0].ended_at.endswith("17:00:00")


def test_edit_requires_start_or_end(cli_env):
    runner.invoke(app, ["start", "ProjectX", "Task1"], input="y\n2606-151\ny\n\n\n")
    conn = db.get_connection(cli_env)
    entry_id = db.get_running_entry(conn).id

    result = runner.invoke(app, ["edit", str(entry_id)])

    assert result.exit_code == 1
    assert "provide --start and/or --end" in result.output


def test_edit_rejects_start_after_end(cli_env):
    runner.invoke(app, ["start", "ProjectX", "Task1"], input="y\n2606-151\ny\n\n\n")
    runner.invoke(app, ["stop", "--at", "09:30"])
    conn = db.get_connection(cli_env)
    entry_id = db.list_entries(conn)[0].id

    result = runner.invoke(app, ["edit", str(entry_id), "--start", "10:00"])

    assert result.exit_code == 1
    assert "start must be before end" in result.output


def test_edit_unparseable_time_is_an_error(cli_env):
    runner.invoke(app, ["start", "ProjectX", "Task1"], input="y\n2606-151\ny\n\n\n")
    conn = db.get_connection(cli_env)
    entry_id = db.get_running_entry(conn).id

    result = runner.invoke(app, ["edit", str(entry_id), "--end", "not-a-time"])

    assert result.exit_code == 1


def test_start_creates_subtask_with_case_task_and_work_type(cli_env):
    result = runner.invoke(
        app, ["start", "2606-151", "PLC"], input="y\n2606-151\ny\n1112\n1170\n"
    )

    assert result.exit_code == 0
    conn = db.get_connection(cli_env)
    project = db.get_project_by_name(conn, "2606-151")
    subtask = db.get_subtask_by_name(conn, project.id, "PLC")
    assert subtask.case_task == "1112"
    assert subtask.work_type == "1170"


def test_start_at_backdates_start_time(cli_env):
    result = runner.invoke(app, ["start", "ProjectX", "Task1", "--at", "07:00"], input="y\n2606-151\ny\n\n\n")

    assert result.exit_code == 0
    conn = db.get_connection(cli_env)
    running = db.get_running_entry(conn)
    assert running.started_at.endswith("07:00:00")


def test_start_at_rejects_overlap_with_existing_entry(cli_env):
    conn = db.get_connection(cli_env)
    project = db.create_project(conn, "ProjectX")
    subtask = db.create_subtask(conn, project.id, "Task1")
    today = datetime.now().date().isoformat()
    conn.execute(
        "INSERT INTO time_entries (subtask_id, started_at, ended_at) VALUES (?, ?, ?)",
        (subtask.id, f"{today}T09:00:00", f"{today}T10:00:00"),
    )
    conn.commit()

    result = runner.invoke(app, ["start", "ProjectX", "Task1", "--at", "09:30"], input="3\n")

    assert result.exit_code == 1
    assert "Overlaps entry" in result.output
    conn = db.get_connection(cli_env)
    assert db.get_running_entry(conn) is None


def test_start_at_overlap_trim_shrinks_existing_entry(cli_env):
    conn = db.get_connection(cli_env)
    project = db.create_project(conn, "ProjectX")
    subtask = db.create_subtask(conn, project.id, "Task1")
    conflict = db.add_entry(
        conn, subtask.id, datetime(2026, 8, 10, 9, 0, 0), datetime(2026, 8, 10, 10, 0, 0)
    )

    result = runner.invoke(
        app,
        ["start", "ProjectX", "Task1", "--at", "2026-08-10 09:30"],
        input="1\n",
    )

    assert result.exit_code == 0
    conn = db.get_connection(cli_env)
    running = db.get_running_entry(conn)
    assert running.started_at == "2026-08-10T09:30:00"
    trimmed = db.get_entry(conn, conflict.id)
    assert trimmed.ended_at == "2026-08-10T09:30:00"


def test_start_at_overlap_clip_starts_after_conflict(cli_env):
    conn = db.get_connection(cli_env)
    project = db.create_project(conn, "ProjectX")
    subtask = db.create_subtask(conn, project.id, "Task1")
    conflict = db.add_entry(
        conn, subtask.id, datetime(2026, 8, 10, 9, 0, 0), datetime(2026, 8, 10, 10, 0, 0)
    )

    result = runner.invoke(
        app,
        ["start", "ProjectX", "Task1", "--at", "2026-08-10 09:30"],
        input="2\n",
    )

    assert result.exit_code == 0
    conn = db.get_connection(cli_env)
    running = db.get_running_entry(conn)
    assert running.started_at == "2026-08-10T10:00:00"
    untouched = db.get_entry(conn, conflict.id)
    assert untouched.ended_at == "2026-08-10T10:00:00"


def test_stop_at_overlap_trim_pushes_existing_entry_start_forward(cli_env):
    conn = db.get_connection(cli_env)
    project = db.create_project(conn, "ProjectX")
    subtask = db.create_subtask(conn, project.id, "Task1")
    db.start_timer(conn, subtask.id, datetime(2026, 8, 10, 9, 0, 0))
    conn.execute(
        "INSERT INTO time_entries (subtask_id, started_at, ended_at) VALUES (?, ?, ?)",
        (subtask.id, "2026-08-10T10:30:00", "2026-08-10T12:00:00"),
    )
    conn.commit()

    result = runner.invoke(app, ["stop", "--at", "2026-08-10 11:00"], input="1\n")

    assert result.exit_code == 0
    conn = db.get_connection(cli_env)
    entries = db.list_entries(conn)
    stopped = next(e for e in entries if e.started_at == "2026-08-10T09:00:00")
    assert stopped.ended_at == "2026-08-10T11:00:00"
    trimmed = next(e for e in entries if e.id != stopped.id)
    assert trimmed.started_at == "2026-08-10T11:00:00"
    assert trimmed.ended_at == "2026-08-10T12:00:00"


def test_stop_at_overlap_clip_caps_stop_time_before_conflict(cli_env):
    conn = db.get_connection(cli_env)
    project = db.create_project(conn, "ProjectX")
    subtask = db.create_subtask(conn, project.id, "Task1")
    db.start_timer(conn, subtask.id, datetime(2026, 8, 10, 9, 0, 0))
    conn.execute(
        "INSERT INTO time_entries (subtask_id, started_at, ended_at) VALUES (?, ?, ?)",
        (subtask.id, "2026-08-10T10:30:00", "2026-08-10T12:00:00"),
    )
    conn.commit()

    result = runner.invoke(app, ["stop", "--at", "2026-08-10 11:00"], input="2\n")

    assert result.exit_code == 0
    conn = db.get_connection(cli_env)
    entries = db.list_entries(conn)
    stopped = next(e for e in entries if e.started_at == "2026-08-10T09:00:00")
    assert stopped.ended_at == "2026-08-10T10:30:00"
    other = next(e for e in entries if e.id != stopped.id)
    assert other.started_at == "2026-08-10T10:30:00"
    assert other.ended_at == "2026-08-10T12:00:00"


def test_edit_overlap_trim_existing_entry(cli_env):
    conn = db.get_connection(cli_env)
    project = db.create_project(conn, "ProjectX")
    subtask = db.create_subtask(conn, project.id, "Task1")
    entry = db.add_entry(
        conn, subtask.id, datetime(2026, 8, 10, 8, 0, 0), datetime(2026, 8, 10, 9, 0, 0)
    )
    conflict = db.add_entry(
        conn, subtask.id, datetime(2026, 8, 10, 10, 0, 0), datetime(2026, 8, 10, 11, 0, 0)
    )

    result = runner.invoke(
        app, ["edit", str(entry.id), "--end", "2026-08-10 10:30"], input="1\n"
    )

    assert result.exit_code == 0
    conn = db.get_connection(cli_env)
    updated_entry = db.get_entry(conn, entry.id)
    assert updated_entry.ended_at == "2026-08-10T10:30:00"
    trimmed_conflict = db.get_entry(conn, conflict.id)
    assert trimmed_conflict.started_at == "2026-08-10T10:30:00"
    assert trimmed_conflict.ended_at == "2026-08-10T11:00:00"


def test_edit_overlap_clip_pulls_end_back_before_conflict(cli_env):
    conn = db.get_connection(cli_env)
    project = db.create_project(conn, "ProjectX")
    subtask = db.create_subtask(conn, project.id, "Task1")
    entry = db.add_entry(
        conn, subtask.id, datetime(2026, 8, 10, 8, 0, 0), datetime(2026, 8, 10, 9, 0, 0)
    )
    conflict = db.add_entry(
        conn, subtask.id, datetime(2026, 8, 10, 10, 0, 0), datetime(2026, 8, 10, 11, 0, 0)
    )

    result = runner.invoke(
        app, ["edit", str(entry.id), "--end", "2026-08-10 10:30"], input="2\n"
    )

    assert result.exit_code == 0
    conn = db.get_connection(cli_env)
    updated_entry = db.get_entry(conn, entry.id)
    assert updated_entry.ended_at == "2026-08-10T10:00:00"
    unchanged_conflict = db.get_entry(conn, conflict.id)
    assert unchanged_conflict.started_at == "2026-08-10T10:00:00"
    assert unchanged_conflict.ended_at == "2026-08-10T11:00:00"


def test_add_overlap_nested_offers_only_cancel(cli_env):
    conn = db.get_connection(cli_env)
    project = db.create_project(conn, "ProjectX", case_number="2606-151")
    subtask = db.create_subtask(conn, project.id, "Task1")
    db.add_entry(conn, subtask.id, datetime(2026, 8, 10, 9, 0, 0), datetime(2026, 8, 10, 12, 0, 0))

    result = runner.invoke(
        app,
        ["add", "ProjectX", "Task1", "--start", "10:00", "--end", "10:30", "--date", "2026-08-10"],
        input="1\n",
    )

    assert result.exit_code == 1
    assert "falls entirely inside entry" in result.output
    conn = db.get_connection(cli_env)
    assert len(db.list_entries(conn)) == 1


def test_add_overlap_swallow_offers_clip_not_trim(cli_env):
    conn = db.get_connection(cli_env)
    project = db.create_project(conn, "ProjectX", case_number="2606-151")
    subtask = db.create_subtask(conn, project.id, "Task1")
    conflict = db.add_entry(
        conn, subtask.id, datetime(2026, 8, 10, 10, 0, 0), datetime(2026, 8, 10, 10, 30, 0)
    )

    result = runner.invoke(
        app,
        ["add", "ProjectX", "Task1", "--start", "09:00", "--end", "12:00", "--date", "2026-08-10"],
        input="2\n",
    )

    assert result.exit_code == 0
    conn = db.get_connection(cli_env)
    entries = db.list_entries(conn)
    new_entry = next(e for e in entries if e.id != conflict.id)
    assert new_entry.started_at == "2026-08-10T09:00:00"
    assert new_entry.ended_at == "2026-08-10T10:00:00"
    unchanged = db.get_entry(conn, conflict.id)
    assert unchanged.started_at == "2026-08-10T10:00:00"
    assert unchanged.ended_at == "2026-08-10T10:30:00"


def test_add_overlap_swallow_trim_choice_is_ignored_as_cancel(cli_env):
    conn = db.get_connection(cli_env)
    project = db.create_project(conn, "ProjectX", case_number="2606-151")
    subtask = db.create_subtask(conn, project.id, "Task1")
    db.add_entry(conn, subtask.id, datetime(2026, 8, 10, 10, 0, 0), datetime(2026, 8, 10, 10, 30, 0))

    result = runner.invoke(
        app,
        ["add", "ProjectX", "Task1", "--start", "09:00", "--end", "12:00", "--date", "2026-08-10"],
        input="1\n",
    )

    assert result.exit_code == 1
    conn = db.get_connection(cli_env)
    assert len(db.list_entries(conn)) == 1


def test_subtask_edit_sets_fields(cli_env):
    conn = db.get_connection(cli_env)
    project = db.create_project(conn, "ProjectX")
    db.create_subtask(conn, project.id, "Task1")

    result = runner.invoke(
        app, ["subtask", "edit", "ProjectX", "Task1", "--case-task", "1", "--work-type", "9000"]
    )

    assert result.exit_code == 0
    conn = db.get_connection(cli_env)
    subtask = db.get_subtask_by_name(conn, project.id, "Task1")
    assert subtask.case_task == "1"
    assert subtask.work_type == "9000"


def test_subtask_edit_renames(cli_env):
    conn = db.get_connection(cli_env)
    project = db.create_project(conn, "ProjectX")
    db.create_subtask(conn, project.id, "Task1")

    result = runner.invoke(app, ["subtask", "edit", "ProjectX", "Task1", "--name", "Renamed"])

    assert result.exit_code == 0
    conn = db.get_connection(cli_env)
    assert db.get_subtask_by_name(conn, project.id, "Renamed") is not None
    assert db.get_subtask_by_name(conn, project.id, "Task1") is None


def test_subtask_edit_requires_at_least_one_option(cli_env):
    conn = db.get_connection(cli_env)
    project = db.create_project(conn, "ProjectX")
    db.create_subtask(conn, project.id, "Task1")

    result = runner.invoke(app, ["subtask", "edit", "ProjectX", "Task1"])

    assert result.exit_code == 1
    assert "provide --case-task, --work-type, and/or --name" in result.output


def test_subtask_edit_missing_project_is_an_error(cli_env):
    result = runner.invoke(app, ["subtask", "edit", "Nonexistent", "Task1", "--name", "X"])

    assert result.exit_code == 1
    assert "No project named 'Nonexistent'" in result.output


def test_subtask_edit_missing_subtask_is_an_error(cli_env):
    conn = db.get_connection(cli_env)
    db.create_project(conn, "ProjectX")

    result = runner.invoke(app, ["subtask", "edit", "ProjectX", "Nonexistent", "--name", "X"])

    assert result.exit_code == 1
    assert "No subtask named 'Nonexistent' under 'ProjectX'" in result.output


def test_delete_removes_entry_when_confirmed(cli_env):
    runner.invoke(app, ["start", "ProjectX", "Task1"], input="y\n2606-151\ny\n\n\n")
    runner.invoke(app, ["stop"])
    conn = db.get_connection(cli_env)
    entry_id = db.list_entries(conn)[0].id

    result = runner.invoke(app, ["delete", str(entry_id)], input="y\n")

    assert result.exit_code == 0
    assert f"Deleted entry {entry_id}" in result.output
    conn = db.get_connection(cli_env)
    assert db.get_entry(conn, entry_id) is None


def test_delete_aborts_when_declined(cli_env):
    runner.invoke(app, ["start", "ProjectX", "Task1"], input="y\n2606-151\ny\n\n\n")
    runner.invoke(app, ["stop"])
    conn = db.get_connection(cli_env)
    entry_id = db.list_entries(conn)[0].id

    result = runner.invoke(app, ["delete", str(entry_id)], input="n\n")

    assert result.exit_code == 1
    conn = db.get_connection(cli_env)
    assert db.get_entry(conn, entry_id) is not None


def test_delete_with_yes_flag_skips_confirmation(cli_env):
    runner.invoke(app, ["start", "ProjectX", "Task1"], input="y\n2606-151\ny\n\n\n")
    runner.invoke(app, ["stop"])
    conn = db.get_connection(cli_env)
    entry_id = db.list_entries(conn)[0].id

    result = runner.invoke(app, ["delete", str(entry_id), "--yes"])

    assert result.exit_code == 0
    conn = db.get_connection(cli_env)
    assert db.get_entry(conn, entry_id) is None


def test_delete_missing_entry_is_an_error(cli_env):
    result = runner.invoke(app, ["delete", "999"])

    assert result.exit_code == 1
    assert "No entry with id 999" in result.output


def test_today_lists_only_todays_entries(cli_env):
    conn = db.get_connection(cli_env)
    project = db.create_project(conn, "ProjectX")
    subtask = db.create_subtask(conn, project.id, "Task1")
    yesterday = datetime.now() - timedelta(days=1)
    db.start_timer(conn, subtask.id, yesterday)
    db.stop_timer(conn, yesterday + timedelta(hours=1))

    runner.invoke(app, ["start", "ProjectX", "Task1"])
    runner.invoke(app, ["stop"])

    result = runner.invoke(app, ["today"])

    assert result.exit_code == 0
    lines = [line for line in result.output.splitlines() if "ProjectX" in line]
    assert len(lines) == 1


def test_multiple_same_day_sessions_stay_separate_in_today_and_week_but_sum_in_table(cli_env):
    conn = db.get_connection(cli_env)
    project = db.create_project(conn, "2606-151", case_number="2606-151")
    subtask = db.create_subtask(conn, project.id, "PLC", case_task="1112", work_type="1170")
    today = datetime.now()
    session1_start = today.replace(hour=9, minute=0, second=0, microsecond=0)
    session2_start = today.replace(hour=11, minute=0, second=0, microsecond=0)
    db.start_timer(conn, subtask.id, session1_start)
    db.stop_timer(conn, session1_start + timedelta(minutes=30))  # 0.5h
    db.start_timer(conn, subtask.id, session2_start)
    db.stop_timer(conn, session2_start + timedelta(minutes=45))  # 0.75h

    today_lines = [
        line for line in runner.invoke(app, ["today"]).output.splitlines() if "2606-151" in line
    ]
    week_lines = [
        line for line in runner.invoke(app, ["week"]).output.splitlines() if "2606-151" in line
    ]
    table_output = runner.invoke(app, ["week", "--table"]).output

    assert len(today_lines) == 2
    assert len(week_lines) == 2

    table_lines = [line for line in table_output.splitlines() if "2606-151" in line]
    assert len(table_lines) == 1
    cells = table_lines[0].split("\t")
    assert cells[:5] == ["Sag", "2606-151", "1112", "1170", "PLC"]
    day_index = today.weekday()
    assert cells[5 + day_index] == "1,25"


def test_week_lists_current_week_by_default(cli_env):
    runner.invoke(app, ["start", "ProjectX", "Task1"], input="y\n2606-151\ny\n\n\n")
    runner.invoke(app, ["stop"])

    result = runner.invoke(app, ["week"])

    assert result.exit_code == 0
    assert "ProjectX/Task1" in result.output


def test_week_last_shows_previous_week(cli_env):
    conn = db.get_connection(cli_env)
    project = db.create_project(conn, "ProjectX")
    subtask = db.create_subtask(conn, project.id, "Task1")
    last_week = datetime.now() - timedelta(days=7)
    db.start_timer(conn, subtask.id, last_week)
    db.stop_timer(conn, last_week + timedelta(hours=1))

    result_this_week = runner.invoke(app, ["week"])
    result_last_week = runner.invoke(app, ["week", "last"])

    assert "No entries yet" in result_this_week.output
    assert "ProjectX/Task1" in result_last_week.output


def test_week_invalid_arg_is_an_error(cli_env):
    result = runner.invoke(app, ["week", "not-a-week"])

    assert result.exit_code == 1
    assert "invalid week" in result.output


def test_week_table_matches_finance_report_format(cli_env):
    conn = db.get_connection(cli_env)
    project = db.create_project(conn, "2606-151", case_number="2606-151")
    subtask = db.create_subtask(conn, project.id, "PLC", case_task="1112", work_type="1170")
    monday = datetime.now() - timedelta(days=datetime.now().weekday())
    monday_start = datetime(monday.year, monday.month, monday.day, 8, 0, 0)
    db.start_timer(conn, subtask.id, monday_start)
    db.stop_timer(conn, monday_start + timedelta(hours=4, minutes=30))

    result = runner.invoke(app, ["week", "--table"])

    assert result.exit_code == 0
    lines = result.output.splitlines()
    assert lines[0].split("\t")[:5] == ["Type", "Sagsnr.", "Sagsopgave", "Arbejdstype", "Beskrivelse"]
    data_line = next(line for line in lines if "2606-151" in line)
    cells = data_line.split("\t")
    assert cells[:5] == ["Sag", "2606-151", "1112", "1170", "PLC"]
    assert cells[5] == "4,5"


def test_week_copy_without_table_is_an_error(cli_env):
    result = runner.invoke(app, ["week", "--copy"])

    assert result.exit_code == 1
    assert "requires --table" in result.output


def test_week_table_copy_calls_clipboard_with_table_text(cli_env, monkeypatch):
    conn = db.get_connection(cli_env)
    project = db.create_project(conn, "2606-151", case_number="2606-151")
    subtask = db.create_subtask(conn, project.id, "PLC", case_task="1112", work_type="1170")
    monday = datetime.now() - timedelta(days=datetime.now().weekday())
    monday_start = datetime(monday.year, monday.month, monday.day, 8, 0, 0)
    db.start_timer(conn, subtask.id, monday_start)
    db.stop_timer(conn, monday_start + timedelta(hours=4, minutes=30))

    captured = {}

    def fake_copy(text):
        captured["text"] = text

    monkeypatch.setattr("time_tracker_app.cli._copy_to_clipboard", fake_copy)

    result = runner.invoke(app, ["week", "--table", "--copy"])

    assert result.exit_code == 0
    assert "(copied to clipboard, header excluded)" in result.output
    assert "text" in captured
    assert "Type" not in captured["text"]
    assert "Sagsnr." not in captured["text"]
    lines = captured["text"].splitlines()
    assert len(lines) == 1
    assert lines[0].split("\t")[:5] == ["Sag", "2606-151", "1112", "1170", "PLC"]


def test_week_table_copy_reports_failure_gracefully(cli_env, monkeypatch):
    def fake_copy(text):
        raise RuntimeError("clipboard unavailable")

    monkeypatch.setattr("time_tracker_app.cli._copy_to_clipboard", fake_copy)

    result = runner.invoke(app, ["week", "--table", "--copy"])

    assert result.exit_code == 0
    assert "Warning: could not copy to clipboard" in result.output


def test_week_table_uses_case_number_not_project_name_for_sagsnr(cli_env):
    conn = db.get_connection(cli_env)
    project = db.create_project(conn, "PLC Work", case_number="2606-151")
    subtask = db.create_subtask(conn, project.id, "PLC", case_task="1112", work_type="1170")
    monday = datetime.now() - timedelta(days=datetime.now().weekday())
    monday_start = datetime(monday.year, monday.month, monday.day, 8, 0, 0)
    db.start_timer(conn, subtask.id, monday_start)
    db.stop_timer(conn, monday_start + timedelta(hours=2))

    result = runner.invoke(app, ["week", "--table"])

    assert result.exit_code == 0
    assert "PLC Work" not in result.output
    data_line = next(line for line in result.output.splitlines() if "2606-151" in line)
    assert data_line.split("\t")[:2] == ["Sag", "2606-151"]


def test_project_edit_sets_case_number(cli_env):
    conn = db.get_connection(cli_env)
    db.create_project(conn, "PLC Work")

    result = runner.invoke(app, ["project", "edit", "PLC Work", "--case-number", "2606-151"])

    assert result.exit_code == 0
    conn = db.get_connection(cli_env)
    assert db.get_project_by_name(conn, "PLC Work").case_number == "2606-151"


def test_project_edit_renames_project(cli_env):
    conn = db.get_connection(cli_env)
    db.create_project(conn, "2606-151 - Cimbria")

    result = runner.invoke(app, ["project", "edit", "2606-151 - Cimbria", "--name", "Cimbria"])

    assert result.exit_code == 0
    conn = db.get_connection(cli_env)
    assert db.get_project_by_name(conn, "Cimbria") is not None
    assert db.get_project_by_name(conn, "2606-151 - Cimbria") is None


def test_project_edit_requires_at_least_one_option(cli_env):
    conn = db.get_connection(cli_env)
    db.create_project(conn, "PLC Work")

    result = runner.invoke(app, ["project", "edit", "PLC Work"])

    assert result.exit_code == 1
    assert "provide --case-number and/or --name" in result.output


def test_project_edit_missing_project_is_an_error(cli_env):
    result = runner.invoke(app, ["project", "edit", "Nonexistent", "--case-number", "2606-151"])

    assert result.exit_code == 1
    assert "No project named 'Nonexistent'" in result.output


def test_project_list_shows_all_projects(cli_env):
    conn = db.get_connection(cli_env)
    db.create_project(conn, "ProjectB", case_number="2222-222")
    db.create_project(conn, "ProjectA", case_number="1111-111")

    result = runner.invoke(app, ["project", "list"])

    assert result.exit_code == 0
    lines = result.output.splitlines()
    assert lines[0].startswith("ProjectA")
    assert "1111-111" in lines[0]
    assert lines[1].startswith("ProjectB")
    assert "2222-222" in lines[1]


def test_project_list_empty_message(cli_env):
    result = runner.invoke(app, ["project", "list"])

    assert result.exit_code == 0
    assert "No projects yet" in result.output


def test_project_list_shows_subtasks_for_given_project(cli_env):
    conn = db.get_connection(cli_env)
    project = db.create_project(conn, "ProjectX", case_number="2606-151")
    db.create_subtask(conn, project.id, "Task1", case_task="1", work_type="9000")

    result = runner.invoke(app, ["project", "list", "ProjectX"])

    assert result.exit_code == 0
    assert "ProjectX" in result.output
    assert "2606-151" in result.output
    assert "Task1" in result.output
    assert "Sagsopgave: 1" in result.output
    assert "Arbejdstype: 9000" in result.output


def test_project_list_shows_no_subtasks_message(cli_env):
    conn = db.get_connection(cli_env)
    db.create_project(conn, "ProjectX", case_number="2606-151")

    result = runner.invoke(app, ["project", "list", "ProjectX"])

    assert result.exit_code == 0
    assert "(no subtasks)" in result.output


def test_project_list_unknown_name_is_error(cli_env):
    result = runner.invoke(app, ["project", "list", "Nonexistent"])

    assert result.exit_code == 1
    assert "No project named 'Nonexistent'" in result.output


def test_project_create_creates_project(cli_env):
    result = runner.invoke(app, ["project", "create", "ProjectX", "--case-number", "2606-151"])

    assert result.exit_code == 0
    conn = db.get_connection(cli_env)
    project = db.get_project_by_name(conn, "ProjectX")
    assert project is not None
    assert project.case_number == "2606-151"


def test_project_create_duplicate_name_is_error(cli_env):
    conn = db.get_connection(cli_env)
    db.create_project(conn, "ProjectX")

    result = runner.invoke(app, ["project", "create", "ProjectX", "--case-number", "2606-151"])

    assert result.exit_code == 1
    assert "already exists" in result.output


def test_project_create_missing_case_number_is_a_usage_error(cli_env):
    result = runner.invoke(app, ["project", "create", "ProjectX"])

    assert result.exit_code != 0


def test_project_delete_with_no_subtasks_confirms_and_deletes(cli_env):
    conn = db.get_connection(cli_env)
    db.create_project(conn, "ProjectX")

    result = runner.invoke(app, ["project", "delete", "ProjectX"], input="y\n")

    assert result.exit_code == 0
    conn = db.get_connection(cli_env)
    assert db.get_project_by_name(conn, "ProjectX") is None


def test_project_delete_declined_confirmation_aborts(cli_env):
    conn = db.get_connection(cli_env)
    db.create_project(conn, "ProjectX")

    result = runner.invoke(app, ["project", "delete", "ProjectX"], input="n\n")

    assert result.exit_code == 1
    conn = db.get_connection(cli_env)
    assert db.get_project_by_name(conn, "ProjectX") is not None


def test_project_delete_with_yes_skips_confirmation(cli_env):
    conn = db.get_connection(cli_env)
    db.create_project(conn, "ProjectX")

    result = runner.invoke(app, ["project", "delete", "ProjectX", "--yes"])

    assert result.exit_code == 0
    conn = db.get_connection(cli_env)
    assert db.get_project_by_name(conn, "ProjectX") is None


def test_project_delete_blocks_when_has_subtasks_without_force(cli_env):
    conn = db.get_connection(cli_env)
    project = db.create_project(conn, "ProjectX")
    db.create_subtask(conn, project.id, "Task1")

    result = runner.invoke(app, ["project", "delete", "ProjectX"])

    assert result.exit_code == 1
    assert "Use --force" in result.output
    conn = db.get_connection(cli_env)
    assert db.get_project_by_name(conn, "ProjectX") is not None


def test_project_delete_cascades_with_force(cli_env):
    conn = db.get_connection(cli_env)
    project = db.create_project(conn, "ProjectX")
    subtask = db.create_subtask(conn, project.id, "Task1")
    db.add_entry(conn, subtask.id, datetime(2026, 8, 13, 9, 0, 0), datetime(2026, 8, 13, 10, 0, 0))

    result = runner.invoke(app, ["project", "delete", "ProjectX", "--force", "--yes"])

    assert result.exit_code == 0
    conn = db.get_connection(cli_env)
    assert db.get_project_by_name(conn, "ProjectX") is None
    assert db.list_subtasks(conn, project.id) == []


def test_project_delete_missing_project_is_error(cli_env):
    result = runner.invoke(app, ["project", "delete", "Nonexistent"])

    assert result.exit_code == 1
    assert "No project named 'Nonexistent'" in result.output
