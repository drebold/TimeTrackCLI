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
