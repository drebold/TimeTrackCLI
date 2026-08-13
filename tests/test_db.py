def test_init_db_creates_tables(conn):
    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert {"projects", "subtasks", "time_entries"} <= tables


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


from datetime import datetime

import pytest


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


def test_list_entries_breaks_same_second_ties_by_creation_order(conn):
    subtask = _make_subtask(conn, "ProjectX", "Task1")
    same_second = datetime(2026, 8, 13, 9, 0, 0)
    first = db.start_timer(conn, subtask.id, same_second)
    db.stop_timer(conn, same_second)
    second = db.start_timer(conn, subtask.id, same_second)
    db.stop_timer(conn, same_second)

    entries = db.list_entries(conn)

    assert entries[0].id == second.id
    assert entries[1].id == first.id


def test_get_subtask_project_names(conn):
    subtask = _make_subtask(conn, "ProjectX", "Task1")
    project_name, subtask_name = db.get_subtask_project_names(conn, subtask.id)
    assert project_name == "ProjectX"
    assert subtask_name == "Task1"


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


def test_create_subtask_stores_case_task_and_work_type(conn):
    project = db.create_project(conn, "2606-151", case_number="2606-151")
    subtask = db.create_subtask(conn, project.id, "PLC", case_task="1112", work_type="1170")

    fetched = db.get_subtask_by_name(conn, project.id, "PLC")
    assert fetched.case_task == "1112"
    assert fetched.work_type == "1170"

    by_id = db.get_subtask(conn, subtask.id)
    assert by_id.case_task == "1112"
    assert by_id.work_type == "1170"


def test_create_subtask_case_task_and_work_type_default_to_none(conn):
    project = db.create_project(conn, "ProjectX")
    subtask = db.create_subtask(conn, project.id, "Task1")
    assert subtask.case_task is None
    assert subtask.work_type is None


def test_migrating_old_subtasks_table_adds_missing_columns(tmp_path):
    db_path = tmp_path / "old.db"
    conn = db.get_connection(db_path)
    conn.execute("ALTER TABLE subtasks RENAME TO subtasks_new")
    conn.execute(
        """
        CREATE TABLE subtasks (
            id INTEGER PRIMARY KEY,
            project_id INTEGER NOT NULL REFERENCES projects(id),
            name TEXT NOT NULL,
            UNIQUE (project_id, name)
        )
        """
    )
    conn.execute("DROP TABLE subtasks_new")
    conn.commit()
    conn.close()

    reconnected = db.get_connection(db_path)
    columns = {row[1] for row in reconnected.execute("PRAGMA table_info(subtasks)").fetchall()}
    assert "case_task" in columns
    assert "work_type" in columns

    project = db.create_project(reconnected, "ProjectX")
    subtask = db.create_subtask(reconnected, project.id, "Task1", case_task="1", work_type="9000")
    assert subtask.case_task == "1"


def test_migrating_old_projects_table_adds_case_number_column_without_backfill(tmp_path):
    db_path = tmp_path / "old.db"
    conn = db.get_connection(db_path)
    conn.execute("ALTER TABLE projects RENAME TO projects_new")
    conn.execute(
        """
        CREATE TABLE projects (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL UNIQUE
        )
        """
    )
    conn.execute("INSERT INTO projects (id, name) VALUES (1, '2606-151 - Cimbria')")
    conn.execute("DROP TABLE projects_new")
    conn.commit()
    conn.close()

    reconnected = db.get_connection(db_path)
    columns = {row[1] for row in reconnected.execute("PRAGMA table_info(projects)").fetchall()}
    assert "case_number" in columns

    project = db.get_project_by_name(reconnected, "2606-151 - Cimbria")
    assert project.case_number is None


def test_create_project_stores_case_number(conn):
    db.create_project(conn, "PLC Work", case_number="2606-151")

    fetched = db.get_project_by_name(conn, "PLC Work")
    assert fetched.case_number == "2606-151"


def test_get_project_by_id(conn):
    created = db.create_project(conn, "PLC Work", case_number="2606-151")

    fetched = db.get_project(conn, created.id)
    assert fetched.name == "PLC Work"
    assert fetched.case_number == "2606-151"


def test_get_project_missing_returns_none(conn):
    assert db.get_project(conn, 999) is None


def test_update_project_changes_name_and_case_number(conn):
    project = db.create_project(conn, "PLC Work")

    updated = db.update_project(conn, project.id, name="New Name", case_number="1234-567")

    assert updated.name == "New Name"
    assert updated.case_number == "1234-567"
    fetched = db.get_project(conn, project.id)
    assert fetched.name == "New Name"
    assert fetched.case_number == "1234-567"


def test_update_project_partial_update_leaves_other_field_unchanged(conn):
    project = db.create_project(conn, "PLC Work", case_number="2606-151")

    db.update_project(conn, project.id, case_number="9999-999")
    fetched = db.get_project(conn, project.id)
    assert fetched.name == "PLC Work"
    assert fetched.case_number == "9999-999"

    db.update_project(conn, project.id, name="Renamed")
    fetched = db.get_project(conn, project.id)
    assert fetched.name == "Renamed"
    assert fetched.case_number == "9999-999"


def test_update_project_missing_id_raises(conn):
    with pytest.raises(db.EditError):
        db.update_project(conn, 999, case_number="2606-151")


def test_update_project_rejects_duplicate_name(conn):
    db.create_project(conn, "ProjectA")
    project_b = db.create_project(conn, "ProjectB")

    with pytest.raises(db.EditError):
        db.update_project(conn, project_b.id, name="ProjectA")


def test_start_timer_raises_overlap_error_for_backdated_start_inside_existing_entry(conn):
    subtask = _make_subtask(conn)
    db.start_timer(conn, subtask.id, datetime(2026, 8, 13, 9, 0, 0))
    db.stop_timer(conn, datetime(2026, 8, 13, 10, 0, 0))

    with pytest.raises(db.OverlapError):
        db.start_timer(conn, subtask.id, datetime(2026, 8, 13, 9, 30, 0))


def test_start_timer_allows_backdated_start_in_a_gap(conn):
    subtask = _make_subtask(conn)
    db.start_timer(conn, subtask.id, datetime(2026, 8, 13, 9, 0, 0))
    db.stop_timer(conn, datetime(2026, 8, 13, 10, 0, 0))

    entry = db.start_timer(conn, subtask.id, datetime(2026, 8, 13, 11, 0, 0))
    assert entry.started_at == db.format_dt(datetime(2026, 8, 13, 11, 0, 0))


def test_stop_timer_raises_overlap_error_when_extending_into_existing_entry(conn):
    subtask = _make_subtask(conn)
    running = db.start_timer(conn, subtask.id, datetime(2026, 8, 13, 9, 0, 0))
    # Directly insert a conflicting closed entry - this state shouldn't be reachable
    # through the public API (start/edit both guard against it), but stop_timer should
    # still refuse to create an overlapping range as defense in depth.
    conn.execute(
        "INSERT INTO time_entries (subtask_id, started_at, ended_at) VALUES (?, ?, ?)",
        (
            subtask.id,
            db.format_dt(datetime(2026, 8, 13, 9, 20, 0)),
            db.format_dt(datetime(2026, 8, 13, 9, 40, 0)),
        ),
    )
    conn.commit()

    with pytest.raises(db.OverlapError):
        db.stop_timer(conn, datetime(2026, 8, 13, 9, 30, 0))

    assert db.get_running_entry(conn).id == running.id


def test_update_entry_raises_overlap_error_against_running_entry(conn):
    subtask = _make_subtask(conn)
    other = db.start_timer(conn, subtask.id, datetime(2020, 1, 1, 7, 0, 0))
    db.stop_timer(conn, datetime(2020, 1, 1, 7, 30, 0))
    db.start_timer(conn, subtask.id, datetime(2020, 1, 1, 9, 0, 0))  # still running

    with pytest.raises(db.OverlapError):
        db.update_entry(
            conn, other.id, start=datetime(2020, 1, 1, 9, 15, 0), end=datetime(2020, 1, 1, 9, 45, 0)
        )


def test_update_entry_raises_overlap_error(conn):
    subtask = _make_subtask(conn)
    db.start_timer(conn, subtask.id, datetime(2026, 8, 13, 9, 0, 0))
    db.stop_timer(conn, datetime(2026, 8, 13, 9, 30, 0))
    later = db.start_timer(conn, subtask.id, datetime(2026, 8, 13, 11, 0, 0))
    db.stop_timer(conn, datetime(2026, 8, 13, 12, 0, 0))

    with pytest.raises(db.OverlapError):
        db.update_entry(conn, later.id, start=datetime(2026, 8, 13, 9, 15, 0))


def test_update_entry_editing_own_range_does_not_self_conflict(conn):
    subtask = _make_subtask(conn)
    entry = db.start_timer(conn, subtask.id, datetime(2026, 8, 13, 9, 0, 0))
    db.stop_timer(conn, datetime(2026, 8, 13, 9, 30, 0))

    updated = db.update_entry(conn, entry.id, end=datetime(2026, 8, 13, 9, 45, 0))
    assert updated.ended_at == db.format_dt(datetime(2026, 8, 13, 9, 45, 0))


def test_add_entry_creates_closed_entry(conn):
    subtask = _make_subtask(conn)
    start = datetime(2026, 8, 13, 9, 0, 0)
    end = datetime(2026, 8, 13, 12, 30, 0)

    entry = db.add_entry(conn, subtask.id, start, end)

    assert entry.subtask_id == subtask.id
    assert entry.started_at == db.format_dt(start)
    assert entry.ended_at == db.format_dt(end)
    assert db.get_entry(conn, entry.id).ended_at == db.format_dt(end)


def test_add_entry_does_not_disturb_running_timer(conn):
    subtask = _make_subtask(conn)
    running = db.start_timer(conn, subtask.id, datetime(2026, 8, 13, 9, 0, 0))

    db.add_entry(conn, subtask.id, datetime(2026, 8, 10, 9, 0, 0), datetime(2026, 8, 10, 10, 0, 0))

    assert db.get_running_entry(conn).id == running.id


def test_add_entry_rejects_start_after_end(conn):
    subtask = _make_subtask(conn)
    with pytest.raises(db.EditError):
        db.add_entry(conn, subtask.id, datetime(2026, 8, 13, 10, 0, 0), datetime(2026, 8, 13, 9, 0, 0))


def test_add_entry_rejects_start_equal_end(conn):
    subtask = _make_subtask(conn)
    same = datetime(2026, 8, 13, 9, 0, 0)
    with pytest.raises(db.EditError):
        db.add_entry(conn, subtask.id, same, same)


def test_add_entry_rejects_overlap_with_existing_entry(conn):
    subtask = _make_subtask(conn)
    db.add_entry(conn, subtask.id, datetime(2026, 8, 13, 9, 0, 0), datetime(2026, 8, 13, 10, 0, 0))

    with pytest.raises(db.OverlapError):
        db.add_entry(conn, subtask.id, datetime(2026, 8, 13, 9, 30, 0), datetime(2026, 8, 13, 11, 0, 0))


def test_add_entry_allows_non_overlapping_entry_same_day(conn):
    subtask = _make_subtask(conn)
    db.add_entry(conn, subtask.id, datetime(2026, 8, 13, 9, 0, 0), datetime(2026, 8, 13, 10, 0, 0))

    entry = db.add_entry(conn, subtask.id, datetime(2026, 8, 13, 11, 0, 0), datetime(2026, 8, 13, 12, 0, 0))
    assert entry.id is not None


def test_delete_entry_removes_it(conn):
    subtask = _make_subtask(conn)
    entry = db.start_timer(conn, subtask.id, datetime(2026, 8, 13, 9, 0, 0))
    db.stop_timer(conn, datetime(2026, 8, 13, 9, 30, 0))

    assert db.delete_entry(conn, entry.id) is True
    assert db.get_entry(conn, entry.id) is None


def test_delete_entry_missing_returns_false(conn):
    assert db.delete_entry(conn, 999) is False


def test_list_entries_filters_by_date_range(conn):
    subtask = _make_subtask(conn)
    db.start_timer(conn, subtask.id, datetime(2026, 8, 10, 9, 0, 0))
    db.stop_timer(conn, datetime(2026, 8, 10, 9, 30, 0))
    db.start_timer(conn, subtask.id, datetime(2026, 8, 13, 9, 0, 0))
    db.stop_timer(conn, datetime(2026, 8, 13, 9, 30, 0))
    db.start_timer(conn, subtask.id, datetime(2026, 8, 20, 9, 0, 0))
    db.stop_timer(conn, datetime(2026, 8, 20, 9, 30, 0))

    from datetime import date

    entries = db.list_entries(conn, start_date=date(2026, 8, 13), end_date=date(2026, 8, 13))
    assert len(entries) == 1
    assert entries[0].started_at.startswith("2026-08-13")


def test_get_week_report_groups_and_sums_hours_by_day(conn):
    from datetime import date

    project = db.create_project(conn, "2606-151", case_number="2606-151")
    subtask = db.create_subtask(conn, project.id, "PLC", case_task="1112", work_type="1170")

    db.start_timer(conn, subtask.id, datetime(2026, 8, 10, 8, 0, 0))  # Monday
    db.stop_timer(conn, datetime(2026, 8, 10, 12, 30, 0))  # 4.5h
    db.start_timer(conn, subtask.id, datetime(2026, 8, 11, 8, 0, 0))  # Tuesday
    db.stop_timer(conn, datetime(2026, 8, 11, 16, 0, 0))  # 8h

    monday = date(2026, 8, 10)
    sunday = date(2026, 8, 16)
    report = db.get_week_report(conn, monday, sunday)

    assert len(report) == 1
    row = report[0]
    assert row.sagsnr == "2606-151"
    assert row.sagsopgave == "1112"
    assert row.arbejdstype == "1170"
    assert row.beskrivelse == "PLC"
    assert row.hours_by_day[0] == pytest.approx(4.5)
    assert row.hours_by_day[1] == pytest.approx(8.0)
    assert row.hours_by_day[2] == 0
    assert len(row.hours_by_day) == 7


def test_get_week_report_excludes_entries_outside_range(conn):
    from datetime import date

    subtask = _make_subtask(conn)
    db.start_timer(conn, subtask.id, datetime(2026, 8, 3, 9, 0, 0))  # previous week
    db.stop_timer(conn, datetime(2026, 8, 3, 10, 0, 0))

    report = db.get_week_report(conn, date(2026, 8, 10), date(2026, 8, 16))
    assert report == []
