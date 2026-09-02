"""Headless tests for tui.py, driven via Textual's own test harness
(App.run_test()) - see CLAUDE.md for why this is the approach for this file.
"""

from datetime import datetime, timedelta

from time_tracker_app import db
from time_tracker_app.tui import AddEntryScreen, OverlapResolveScreen, TimeTrackerTUI


def _make_conflict(conn):
    project = db.create_project(conn, "ProjectX", case_number="2606-151")
    subtask = db.create_subtask(conn, project.id, "Task1")
    conflict = db.add_entry(
        conn, subtask.id, datetime(2026, 8, 10, 9, 0, 0), datetime(2026, 8, 10, 10, 0, 0)
    )
    return project, subtask, conflict


async def test_add_entry_overlap_shows_resolve_screen(cli_env):
    conn = db.get_connection(cli_env)
    project, subtask, conflict = _make_conflict(conn)

    app = TimeTrackerTUI()
    async with app.run_test(size=(80, 40)) as pilot:
        app.push_screen(AddEntryScreen())
        await pilot.pause()
        screen = app.screen
        screen.query_one("#entry-project-select").value = project.id
        await pilot.pause()
        screen.query_one("#entry-subtask-select").value = subtask.id
        screen.query_one("#entry-date-input").value = "2026-08-10"
        screen.query_one("#entry-start-input").value = "09:30"
        screen.query_one("#entry-end-input").value = "11:00"

        await pilot.click("#add")
        await pilot.pause()

        assert isinstance(app.screen, OverlapResolveScreen)
        # No entry created yet - still resolving the conflict.
        conn = db.get_connection(cli_env)
        assert len(db.list_entries(conn)) == 1


async def test_add_entry_overlap_trim_button(cli_env):
    conn = db.get_connection(cli_env)
    project, subtask, conflict = _make_conflict(conn)

    app = TimeTrackerTUI()
    async with app.run_test(size=(80, 40)) as pilot:
        app.push_screen(AddEntryScreen())
        await pilot.pause()
        screen = app.screen
        screen.query_one("#entry-project-select").value = project.id
        await pilot.pause()
        screen.query_one("#entry-subtask-select").value = subtask.id
        screen.query_one("#entry-date-input").value = "2026-08-10"
        screen.query_one("#entry-start-input").value = "09:30"
        screen.query_one("#entry-end-input").value = "11:00"

        await pilot.click("#add")
        await pilot.pause()
        await pilot.click("#trim")
        await pilot.pause()

    conn = db.get_connection(cli_env)
    entries = db.list_entries(conn)
    assert len(entries) == 2
    trimmed = db.get_entry(conn, conflict.id)
    assert trimmed.ended_at == "2026-08-10T09:30:00"
    added = next(e for e in entries if e.id != conflict.id)
    assert added.started_at == "2026-08-10T09:30:00"
    assert added.ended_at == "2026-08-10T11:00:00"


async def test_add_entry_overlap_clip_button(cli_env):
    conn = db.get_connection(cli_env)
    project, subtask, conflict = _make_conflict(conn)

    app = TimeTrackerTUI()
    async with app.run_test(size=(80, 40)) as pilot:
        app.push_screen(AddEntryScreen())
        await pilot.pause()
        screen = app.screen
        screen.query_one("#entry-project-select").value = project.id
        await pilot.pause()
        screen.query_one("#entry-subtask-select").value = subtask.id
        screen.query_one("#entry-date-input").value = "2026-08-10"
        screen.query_one("#entry-start-input").value = "09:30"
        screen.query_one("#entry-end-input").value = "11:00"

        await pilot.click("#add")
        await pilot.pause()
        await pilot.click("#clip")
        await pilot.pause()

    conn = db.get_connection(cli_env)
    entries = db.list_entries(conn)
    assert len(entries) == 2
    unchanged = db.get_entry(conn, conflict.id)
    assert unchanged.started_at == "2026-08-10T09:00:00"
    assert unchanged.ended_at == "2026-08-10T10:00:00"
    added = next(e for e in entries if e.id != conflict.id)
    assert added.started_at == "2026-08-10T10:00:00"
    assert added.ended_at == "2026-08-10T11:00:00"


async def test_add_entry_overlap_cancel_returns_to_add_dialog(cli_env):
    conn = db.get_connection(cli_env)
    project, subtask, conflict = _make_conflict(conn)

    app = TimeTrackerTUI()
    async with app.run_test(size=(80, 40)) as pilot:
        app.push_screen(AddEntryScreen())
        await pilot.pause()
        screen = app.screen
        screen.query_one("#entry-project-select").value = project.id
        await pilot.pause()
        screen.query_one("#entry-subtask-select").value = subtask.id
        screen.query_one("#entry-date-input").value = "2026-08-10"
        screen.query_one("#entry-start-input").value = "09:30"
        screen.query_one("#entry-end-input").value = "11:00"

        await pilot.click("#add")
        await pilot.pause()
        await pilot.click("#cancel")
        await pilot.pause()

        # Back on AddEntryScreen (not dismissed), free to try different times.
        assert isinstance(app.screen, AddEntryScreen)

    conn = db.get_connection(cli_env)
    assert len(db.list_entries(conn)) == 1


async def test_start_overlap_resolution_via_clip(cli_env):
    # start-btn always uses the real datetime.now() (no --at equivalent in
    # the TUI), so the conflict must be anchored to "now" too, not a fixed
    # past date, or there'd be no overlap to resolve at all.
    conn = db.get_connection(cli_env)
    project = db.create_project(conn, "ProjectX", case_number="2606-151")
    subtask = db.create_subtask(conn, project.id, "Task1")
    now = datetime.now().replace(microsecond=0)
    conflict = db.add_entry(conn, subtask.id, now, now + timedelta(hours=1))

    app = TimeTrackerTUI()
    async with app.run_test(size=(80, 40)) as pilot:
        app.query_one("#project-select").value = project.id
        await pilot.pause()
        app.query_one("#subtask-select").value = subtask.id
        await pilot.pause()

        await pilot.click("#start-btn")
        await pilot.pause()
        assert isinstance(app.screen, OverlapResolveScreen)
        await pilot.click("#clip")
        await pilot.pause()

    conn = db.get_connection(cli_env)
    running = db.get_running_entry(conn)
    assert running is not None
    assert running.started_at == conflict.ended_at


async def test_stop_overlap_resolution_via_trim(cli_env):
    conn = db.get_connection(cli_env)
    project = db.create_project(conn, "ProjectX", case_number="2606-151")
    subtask = db.create_subtask(conn, project.id, "Task1")
    now = datetime.now().replace(microsecond=0)
    running = db.start_timer(conn, subtask.id, now - timedelta(minutes=30))
    # Direct insert - a normal add_entry here would itself conflict with the
    # still-open running entry, same reasoning as the CLI's equivalent test.
    # Starts slightly before "now" so stopping "now" (what #stop-btn always
    # uses) genuinely extends into it, regardless of small test timing jitter.
    conflict_start = now - timedelta(minutes=15)
    conflict_end = now + timedelta(hours=1)
    conn.execute(
        "INSERT INTO time_entries (subtask_id, started_at, ended_at) VALUES (?, ?, ?)",
        (subtask.id, db.format_dt(conflict_start), db.format_dt(conflict_end)),
    )
    conn.commit()

    app = TimeTrackerTUI()
    async with app.run_test(size=(80, 40)) as pilot:
        await pilot.click("#stop-btn")
        await pilot.pause()
        assert isinstance(app.screen, OverlapResolveScreen)
        await pilot.click("#trim")
        await pilot.pause()

    conn = db.get_connection(cli_env)
    stopped = db.get_entry(conn, running.id)
    assert stopped.ended_at is not None
    trimmed = next(e for e in db.list_entries(conn) if e.id != running.id)
    assert trimmed.started_at == stopped.ended_at


async def test_edit_entry_overlap_resolution(cli_env):
    conn = db.get_connection(cli_env)
    project = db.create_project(conn, "ProjectX", case_number="2606-151")
    subtask = db.create_subtask(conn, project.id, "Task1")
    entry = db.add_entry(
        conn, subtask.id, datetime(2026, 8, 10, 8, 0, 0), datetime(2026, 8, 10, 9, 0, 0)
    )
    conflict = db.add_entry(
        conn, subtask.id, datetime(2026, 8, 10, 10, 0, 0), datetime(2026, 8, 10, 11, 0, 0)
    )

    app = TimeTrackerTUI()
    async with app.run_test(size=(80, 40)) as pilot:
        app.current_view = "all"
        app.refresh_entries()
        await pilot.pause()
        table = app.query_one("#entries-table")
        # Select the row for `entry` (not `conflict`) by its row key.
        for row_index in range(table.row_count):
            row_key = table.coordinate_to_cell_key((row_index, 0)).row_key
            if row_key.value == str(entry.id):
                table.cursor_coordinate = (row_index, 0)
                break

        # Must go through a real keypress (not calling action_edit_selected()
        # directly) - it awaits push_screen_wait internally, which needs to
        # run as a background task via Textual's event dispatch so this test
        # can keep interacting with the screen it pushes. Awaiting it
        # directly here would deadlock: it wouldn't return until the screen
        # it's about to push gets dismissed, which we haven't done yet.
        await pilot.press("e")
        await pilot.pause()

        from time_tracker_app.tui import EditEntryScreen

        assert isinstance(app.screen, EditEntryScreen)
        app.screen.query_one("#end-input").value = "2026-08-10 10:30"
        await pilot.click("#save")
        await pilot.pause()

        assert isinstance(app.screen, OverlapResolveScreen)
        await pilot.click("#clip")
        await pilot.pause()

    conn = db.get_connection(cli_env)
    updated = db.get_entry(conn, entry.id)
    assert updated.ended_at == "2026-08-10T10:00:00"
    unchanged_conflict = db.get_entry(conn, conflict.id)
    assert unchanged_conflict.started_at == "2026-08-10T10:00:00"
