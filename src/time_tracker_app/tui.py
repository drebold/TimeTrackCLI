"""Interactive terminal UI, built on Textual, for the time tracker.

Wraps the same `db` module the CLI (`cli.py`) uses directly - no subprocess
calls to `tt`, no duplicated business logic. One sqlite3 connection is opened
for the lifetime of the app (`db.get_db_path()` still honours `TT_DB_PATH`).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    RadioButton,
    RadioSet,
    Select,
    Static,
    TabbedContent,
    TabPane,
)

from time_tracker_app import db
from time_tracker_app.cli import _copy_to_clipboard, _day_header, _format_hours
from time_tracker_app.timeparse import TimeParseError, parse_time_input

NEW_PROJECT = "__new_project__"
NEW_SUBTASK = "__new_subtask__"


def _fmt_duration(td: timedelta) -> str:
    total_seconds = int(td.total_seconds())
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours}:{minutes:02d}:{seconds:02d}"


# -- modal screens --------------------------------------------------------


class ConfirmScreen(ModalScreen[bool]):
    def __init__(self, message: str) -> None:
        super().__init__()
        self.message = message

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label(self.message, id="dialog-message")
            with Horizontal(id="dialog-buttons"):
                yield Button("Cancel", id="cancel")
                yield Button("Delete", variant="error", id="confirm")

    @on(Button.Pressed, "#confirm")
    def confirm(self) -> None:
        self.dismiss(True)

    @on(Button.Pressed, "#cancel")
    def cancel(self) -> None:
        self.dismiss(False)


class NewProjectScreen(ModalScreen[db.Project | None]):
    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label("New project", id="dialog-message")
            yield Input(placeholder="Name", id="name-input")
            yield Input(placeholder="Sagsnr. (case number)", id="case-number-input")
            with Horizontal(id="dialog-buttons"):
                yield Button("Cancel", id="cancel")
                yield Button("Create", variant="success", id="create")

    def on_mount(self) -> None:
        self.query_one("#name-input", Input).focus()

    @on(Button.Pressed, "#create")
    def create(self) -> None:
        conn = self.app.conn  # type: ignore[attr-defined]
        name = self.query_one("#name-input", Input).value.strip()
        if not name:
            return
        if db.get_project_by_name(conn, name) is not None:
            self.query_one("#dialog-message", Label).update(f"Project '{name}' already exists")
            return
        case_number = self.query_one("#case-number-input", Input).value.strip() or None
        project = db.create_project(conn, name, case_number=case_number)
        self.dismiss(project)

    @on(Button.Pressed, "#cancel")
    def cancel(self) -> None:
        self.dismiss(None)


class EditProjectScreen(ModalScreen[db.Project | None]):
    def __init__(self, project: db.Project) -> None:
        super().__init__()
        self.project = project

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label(f"Edit project '{self.project.name}'", id="dialog-message")
            yield Input(value=self.project.name, placeholder="Name", id="name-input")
            yield Input(
                value=self.project.case_number or "",
                placeholder="Sagsnr. (case number)",
                id="case-number-input",
            )
            with Horizontal(id="dialog-buttons"):
                yield Button("Cancel", id="cancel")
                yield Button("Save", variant="success", id="save")

    def on_mount(self) -> None:
        self.query_one("#name-input", Input).focus()

    @on(Button.Pressed, "#save")
    def save(self) -> None:
        conn = self.app.conn  # type: ignore[attr-defined]
        name = self.query_one("#name-input", Input).value.strip()
        if not name:
            return
        case_number = self.query_one("#case-number-input", Input).value.strip() or None
        try:
            updated = db.update_project(conn, self.project.id, name=name, case_number=case_number)
        except db.EditError as e:
            self.query_one("#dialog-message", Label).update(str(e))
            return
        self.dismiss(updated)

    @on(Button.Pressed, "#cancel")
    def cancel(self) -> None:
        self.dismiss(None)


class NewSubtaskScreen(ModalScreen[db.Subtask | None]):
    def __init__(self, project: db.Project) -> None:
        super().__init__()
        self.project = project

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label(f"New subtask under '{self.project.name}'", id="dialog-message")
            yield Input(placeholder="Name", id="name-input")
            yield Input(placeholder="Sagsopgave (task no., optional)", id="case-task-input")
            yield Input(placeholder="Arbejdstype (work-type code, optional)", id="work-type-input")
            with Horizontal(id="dialog-buttons"):
                yield Button("Cancel", id="cancel")
                yield Button("Create", variant="success", id="create")

    def on_mount(self) -> None:
        self.query_one("#name-input", Input).focus()

    @on(Button.Pressed, "#create")
    def create(self) -> None:
        conn = self.app.conn  # type: ignore[attr-defined]
        name = self.query_one("#name-input", Input).value.strip()
        if not name:
            return
        if db.get_subtask_by_name(conn, self.project.id, name) is not None:
            self.query_one("#dialog-message", Label).update(f"Subtask '{name}' already exists")
            return
        case_task = self.query_one("#case-task-input", Input).value.strip() or None
        work_type = self.query_one("#work-type-input", Input).value.strip() or None
        subtask = db.create_subtask(
            conn, self.project.id, name, case_task=case_task, work_type=work_type
        )
        self.dismiss(subtask)

    @on(Button.Pressed, "#cancel")
    def cancel(self) -> None:
        self.dismiss(None)


class EditSubtaskScreen(ModalScreen[db.Subtask | None]):
    def __init__(self, subtask: db.Subtask) -> None:
        super().__init__()
        self.subtask = subtask

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label(f"Edit subtask '{self.subtask.name}'", id="dialog-message")
            yield Input(value=self.subtask.name, placeholder="Name", id="name-input")
            yield Input(
                value=self.subtask.case_task or "",
                placeholder="Sagsopgave (task no., optional)",
                id="case-task-input",
            )
            yield Input(
                value=self.subtask.work_type or "",
                placeholder="Arbejdstype (work-type code, optional)",
                id="work-type-input",
            )
            with Horizontal(id="dialog-buttons"):
                yield Button("Cancel", id="cancel")
                yield Button("Save", variant="success", id="save")

    def on_mount(self) -> None:
        self.query_one("#name-input", Input).focus()

    @on(Button.Pressed, "#save")
    def save(self) -> None:
        conn = self.app.conn  # type: ignore[attr-defined]
        name = self.query_one("#name-input", Input).value.strip()
        if not name:
            return
        case_task = self.query_one("#case-task-input", Input).value.strip() or None
        work_type = self.query_one("#work-type-input", Input).value.strip() or None
        try:
            updated = db.update_subtask(
                conn, self.subtask.id, name=name, case_task=case_task, work_type=work_type
            )
        except db.EditError as e:
            self.query_one("#dialog-message", Label).update(str(e))
            return
        self.dismiss(updated)

    @on(Button.Pressed, "#cancel")
    def cancel(self) -> None:
        self.dismiss(None)


class EditEntryScreen(ModalScreen[tuple[str, str] | None]):
    """Returns (start_text, end_text); blank text means "leave unchanged"."""

    def __init__(self, entry: db.TimeEntry) -> None:
        super().__init__()
        self.entry = entry

    def compose(self) -> ComposeResult:
        started = db.parse_dt(self.entry.started_at)
        ended = db.parse_dt(self.entry.ended_at) if self.entry.ended_at else None
        with Vertical(id="dialog"):
            yield Label(f"Edit entry {self.entry.id}", id="dialog-message")
            yield Input(value=started.strftime("%Y-%m-%d %H:%M"), id="start-input")
            yield Input(
                value=ended.strftime("%Y-%m-%d %H:%M") if ended else "",
                placeholder="(running)",
                id="end-input",
            )
            with Horizontal(id="dialog-buttons"):
                yield Button("Cancel", id="cancel")
                yield Button("Save", variant="success", id="save")

    @on(Button.Pressed, "#save")
    def save(self) -> None:
        start_value = self.query_one("#start-input", Input).value.strip()
        end_value = self.query_one("#end-input", Input).value.strip()
        self.dismiss((start_value, end_value))

    @on(Button.Pressed, "#cancel")
    def cancel(self) -> None:
        self.dismiss(None)


class AddEntryScreen(ModalScreen[bool]):
    """Add a complete entry directly, without touching the running timer.

    Mirrors `tt add`. Dismisses with True if an entry was created.
    """

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label("Add entry", id="dialog-message")
            yield Select([], prompt="Project", id="entry-project-select")
            yield Select([], prompt="Subtask", id="entry-subtask-select", disabled=True)
            yield Input(placeholder="Date YYYY-MM-DD (default: today)", id="entry-date-input")
            yield Input(placeholder="Start, e.g. 09:00", id="entry-start-input")
            yield Input(placeholder="End, e.g. 17:00", id="entry-end-input")
            yield Label("", id="entry-error-label")
            with Horizontal(id="dialog-buttons"):
                yield Button("Cancel", id="cancel")
                yield Button("Add", variant="success", id="add")

    def on_mount(self) -> None:
        self.selected_project: db.Project | None = None
        self._reload_projects()

    def _reload_projects(self, select_id: int | None = None) -> None:
        conn = self.app.conn  # type: ignore[attr-defined]
        select = self.query_one("#entry-project-select", Select)
        projects = db.list_projects(conn)
        select.set_options([("+ New project...", NEW_PROJECT)] + [(p.name, p.id) for p in projects])
        if select_id is not None:
            select.value = select_id

    def _reload_subtasks(self, project_id: int, select_id: int | None = None) -> None:
        conn = self.app.conn  # type: ignore[attr-defined]
        select = self.query_one("#entry-subtask-select", Select)
        subtasks = db.list_subtasks(conn, project_id)
        select.set_options([("+ New subtask...", NEW_SUBTASK)] + [(s.name, s.id) for s in subtasks])
        select.disabled = False
        if select_id is not None:
            select.value = select_id

    @on(Select.Changed, "#entry-project-select")
    def on_project_changed(self, event: Select.Changed) -> None:
        subtask_select = self.query_one("#entry-subtask-select", Select)
        value = event.value
        if value is Select.NULL:
            self.selected_project = None
            subtask_select.set_options([])
            subtask_select.disabled = True
            return
        if value == NEW_PROJECT:
            self.app.push_screen(NewProjectScreen(), self._on_new_project)
            return
        self.selected_project = db.get_project(self.app.conn, value)  # type: ignore[attr-defined]
        if self.selected_project is not None:
            self._reload_subtasks(self.selected_project.id)

    def _on_new_project(self, project: db.Project | None) -> None:
        if project is None:
            self.query_one("#entry-project-select", Select).value = Select.NULL
            return
        self._reload_projects(select_id=project.id)

    @on(Select.Changed, "#entry-subtask-select")
    def on_subtask_changed(self, event: Select.Changed) -> None:
        if event.value == NEW_SUBTASK and self.selected_project is not None:
            self.app.push_screen(NewSubtaskScreen(self.selected_project), self._on_new_subtask)

    def _on_new_subtask(self, subtask: db.Subtask | None) -> None:
        if subtask is None or self.selected_project is None:
            self.query_one("#entry-subtask-select", Select).value = Select.NULL
            return
        self._reload_subtasks(self.selected_project.id, select_id=subtask.id)

    @on(Button.Pressed, "#add")
    def add_entry(self) -> None:
        conn = self.app.conn  # type: ignore[attr-defined]
        error = self.query_one("#entry-error-label", Label)
        subtask_select = self.query_one("#entry-subtask-select", Select)
        subtask_id = subtask_select.value
        if subtask_id is Select.NULL or subtask_id == NEW_SUBTASK:
            error.update("Pick a project and subtask")
            return

        date_raw = self.query_one("#entry-date-input", Input).value.strip()
        start_raw = self.query_one("#entry-start-input", Input).value.strip()
        end_raw = self.query_one("#entry-end-input", Input).value.strip()

        now = datetime.now()
        try:
            start_dt = parse_time_input(start_raw, now)
            end_dt = parse_time_input(end_raw, now)
        except TimeParseError as e:
            error.update(str(e))
            return

        if date_raw:
            try:
                day = datetime.strptime(date_raw, "%Y-%m-%d").date()
            except ValueError:
                error.update(f"Invalid date {date_raw!r} (expected YYYY-MM-DD)")
                return
            start_dt = start_dt.replace(year=day.year, month=day.month, day=day.day)
            end_dt = end_dt.replace(year=day.year, month=day.month, day=day.day)

        try:
            db.add_entry(conn, subtask_id, start_dt, end_dt)
        except (db.EditError, db.OverlapError) as e:
            error.update(str(e))
            return
        self.dismiss(True)

    @on(Button.Pressed, "#cancel")
    def cancel(self) -> None:
        self.dismiss(False)


# -- main app ---------------------------------------------------------------


class TimeTrackerTUI(App):
    CSS_PATH = "tui.tcss"
    TITLE = "tt — Time Tracker"
    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh_all", "Refresh"),
        Binding("a", "add_entry", "Add entry"),
        Binding("d", "delete_selected", "Delete"),
        Binding("e", "edit_selected", "Edit"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.conn = db.get_connection(db.get_db_path())
        self.current_view = "today"
        self.selected_project: db.Project | None = None
        self.running_entry: db.TimeEntry | None = None
        today = date.today()
        self.week_monday = today - timedelta(days=today.weekday())
        self._week_report_rows: list[db.WeekReportRow] = []
        self._week_days: list[date] = []

    def compose(self) -> ComposeResult:
        yield Header()
        with TabbedContent(initial="tab-timer"):
            with TabPane("Timer", id="tab-timer"):
                yield Static("", id="status-label")
                with Horizontal(id="start-panel"):
                    yield Select([], prompt="Project", id="project-select")
                    yield Select([], prompt="Subtask", id="subtask-select", disabled=True)
                    yield Button("Start", variant="success", id="start-btn", disabled=True)
                with Horizontal(id="stop-panel"):
                    yield Button("Stop timer", variant="error", id="stop-btn")
                with Horizontal(id="view-switch-row"):
                    with RadioSet(id="view-switch"):
                        yield RadioButton("Today", value=True, id="view-today")
                        yield RadioButton("This week", id="view-week")
                        yield RadioButton("All", id="view-all")
                    yield Button("Add entry...", id="add-entry-btn")
                yield Label("", id="error-label")
                yield DataTable(id="entries-table")
            with TabPane("Projects", id="tab-projects"):
                with Horizontal(id="projects-layout"):
                    with Vertical(id="projects-pane"):
                        yield Label("Projects", id="projects-label")
                        yield DataTable(id="projects-table")
                        with Horizontal(id="projects-buttons"):
                            yield Button("New...", id="new-project-btn")
                            yield Button("Edit", id="edit-project-btn")
                            yield Button("Delete", variant="error", id="delete-project-btn")
                    with Vertical(id="subtasks-pane"):
                        yield Label("Subtasks", id="subtasks-label")
                        yield DataTable(id="subtasks-table")
                        with Horizontal(id="subtasks-buttons"):
                            yield Button("New...", id="new-subtask-btn")
                            yield Button("Edit", id="edit-subtask-btn")
                yield Label("", id="projects-error-label")
            with TabPane("Week", id="tab-week"):
                with Horizontal(id="week-nav"):
                    yield Button("< Prev", id="week-prev")
                    yield Static("", id="week-label")
                    yield Button("Next >", id="week-next")
                    yield Button("This week", id="week-this")
                    yield Button("Copy to clipboard", id="week-copy")
                yield Label("", id="week-error")
                yield DataTable(id="week-table")
        yield Footer()

    def on_mount(self) -> None:
        entries_table = self.query_one("#entries-table", DataTable)
        entries_table.add_columns("ID", "Project", "Subtask", "Start", "End", "Duration")
        entries_table.cursor_type = "row"

        projects_table = self.query_one("#projects-table", DataTable)
        projects_table.add_columns("ID", "Name", "Sagsnr.", "#Subtasks")
        projects_table.cursor_type = "row"

        subtasks_table = self.query_one("#subtasks-table", DataTable)
        subtasks_table.add_columns("ID", "Name", "Sagsopgave", "Arbejdstype")
        subtasks_table.cursor_type = "row"

        week_table = self.query_one("#week-table", DataTable)
        week_table.cursor_type = "row"

        self.reload_projects()
        self.refresh_status()
        self.refresh_entries()
        self._refresh_projects_table()
        self.refresh_week_table()
        self.set_interval(1, self.tick)

    # -- Timer tab: data loading -------------------------------------------

    def _project_options(self) -> list[tuple[str, object]]:
        projects = db.list_projects(self.conn)
        return [("+ New project...", NEW_PROJECT)] + [(p.name, p.id) for p in projects]

    def reload_projects(self, select_id: int | None = None) -> None:
        select = self.query_one("#project-select", Select)
        select.set_options(self._project_options())
        if select_id is not None:
            select.value = select_id

    def _subtask_options(self, project_id: int) -> list[tuple[str, object]]:
        subtasks = db.list_subtasks(self.conn, project_id)
        return [("+ New subtask...", NEW_SUBTASK)] + [(s.name, s.id) for s in subtasks]

    def reload_subtasks(self, project_id: int, select_id: int | None = None) -> None:
        select = self.query_one("#subtask-select", Select)
        select.set_options(self._subtask_options(project_id))
        select.disabled = False
        if select_id is not None:
            select.value = select_id

    def refresh_status(self) -> None:
        self.running_entry = db.get_running_entry(self.conn)
        start_panel = self.query_one("#start-panel")
        stop_panel = self.query_one("#stop-panel")
        start_panel.display = self.running_entry is None
        stop_panel.display = self.running_entry is not None
        self._update_status_label()

    def _update_status_label(self) -> None:
        label = self.query_one("#status-label", Static)
        if self.running_entry is None:
            label.update("No timer running")
            return
        project_name, subtask_name = db.get_subtask_project_names(
            self.conn, self.running_entry.subtask_id
        )
        started = db.parse_dt(self.running_entry.started_at)
        elapsed = datetime.now() - started
        label.update(f"Running: {project_name}/{subtask_name}   {_fmt_duration(elapsed)}")

    def tick(self) -> None:
        if self.running_entry is not None:
            self._update_status_label()

    def refresh_entries(self) -> None:
        today = date.today()
        if self.current_view == "today":
            entries = db.list_entries(self.conn, start_date=today, end_date=today)
        elif self.current_view == "week":
            monday = today - timedelta(days=today.weekday())
            sunday = monday + timedelta(days=6)
            entries = db.list_entries(self.conn, start_date=monday, end_date=sunday)
        else:
            entries = db.list_entries(self.conn)

        table = self.query_one("#entries-table", DataTable)
        table.clear()
        now = datetime.now()
        for entry in entries:
            started = db.parse_dt(entry.started_at)
            ended = db.parse_dt(entry.ended_at) if entry.ended_at else None
            duration = (ended or now) - started
            table.add_row(
                str(entry.id),
                entry.project_name,
                entry.subtask_name,
                started.strftime("%Y-%m-%d %H:%M"),
                ended.strftime("%H:%M") if ended else "running",
                _fmt_duration(duration),
                key=str(entry.id),
            )

    def _show_error(self, message: str) -> None:
        self.query_one("#error-label", Label).update(message)

    # -- Timer tab: project / subtask selection ------------------------------

    @on(Select.Changed, "#project-select")
    def on_project_changed(self, event: Select.Changed) -> None:
        subtask_select = self.query_one("#subtask-select", Select)
        start_btn = self.query_one("#start-btn", Button)
        value = event.value
        if value is Select.NULL:
            self.selected_project = None
            subtask_select.set_options([])
            subtask_select.disabled = True
            start_btn.disabled = True
            return
        if value == NEW_PROJECT:
            self.push_screen(NewProjectScreen(), self._on_new_project)
            return
        self.selected_project = db.get_project(self.conn, value)
        if self.selected_project is not None:
            self.reload_subtasks(self.selected_project.id)
        start_btn.disabled = True

    def _on_new_project(self, project: db.Project | None) -> None:
        if project is None:
            self.query_one("#project-select", Select).value = Select.NULL
            return
        self.reload_projects(select_id=project.id)
        self._refresh_projects_table()

    @on(Select.Changed, "#subtask-select")
    def on_subtask_changed(self, event: Select.Changed) -> None:
        start_btn = self.query_one("#start-btn", Button)
        value = event.value
        if value is Select.NULL:
            start_btn.disabled = True
            return
        if value == NEW_SUBTASK:
            if self.selected_project is not None:
                self.push_screen(NewSubtaskScreen(self.selected_project), self._on_new_subtask)
            return
        start_btn.disabled = False

    def _on_new_subtask(self, subtask: db.Subtask | None) -> None:
        if subtask is None or self.selected_project is None:
            self.query_one("#subtask-select", Select).value = Select.NULL
            return
        self.reload_subtasks(self.selected_project.id, select_id=subtask.id)
        self._refresh_subtasks_table()

    # -- Timer tab: start / stop ---------------------------------------------

    @on(Button.Pressed, "#start-btn")
    def on_start_pressed(self) -> None:
        subtask_select = self.query_one("#subtask-select", Select)
        subtask_id = subtask_select.value
        if subtask_id is Select.NULL or subtask_id == NEW_SUBTASK:
            return
        try:
            db.start_timer(self.conn, subtask_id, datetime.now())
        except db.OverlapError as e:
            self._show_error(str(e))
            return
        self._show_error("")
        self.refresh_status()
        self.refresh_entries()

    @on(Button.Pressed, "#stop-btn")
    def on_stop_pressed(self) -> None:
        try:
            db.stop_timer(self.conn, datetime.now())
        except db.OverlapError as e:
            self._show_error(str(e))
            return
        self._show_error("")
        self.refresh_status()
        self.refresh_entries()

    @on(Button.Pressed, "#add-entry-btn")
    def on_add_entry_btn(self) -> None:
        self.action_add_entry()

    def action_add_entry(self) -> None:
        def handle(added: bool) -> None:
            if added:
                self.action_refresh_all()

        self.push_screen(AddEntryScreen(), handle)

    # -- Timer tab: view switch -----------------------------------------

    @on(RadioSet.Changed, "#view-switch")
    def on_view_changed(self, event: RadioSet.Changed) -> None:
        view_by_id = {"view-today": "today", "view-week": "week", "view-all": "all"}
        pressed_id = event.pressed.id
        if pressed_id in view_by_id:
            self.current_view = view_by_id[pressed_id]
            self.refresh_entries()

    # -- Timer tab: entry actions ---------------------------------------

    def _selected_entry_id(self) -> int | None:
        table = self.query_one("#entries-table", DataTable)
        if table.row_count == 0:
            return None
        row_key, _ = table.coordinate_to_cell_key(table.cursor_coordinate)
        if row_key.value is None:
            return None
        return int(row_key.value)

    def _delete_selected_time_entry(self) -> None:
        entry_id = self._selected_entry_id()
        if entry_id is None:
            return
        entry = db.get_entry(self.conn, entry_id)
        if entry is None:
            return
        project_name, subtask_name = db.get_subtask_project_names(self.conn, entry.subtask_id)
        end = entry.ended_at or "running"
        message = (
            f"Delete entry {entry_id} ({project_name}/{subtask_name}  "
            f"{entry.started_at} -> {end})?"
        )

        def handle(confirmed: bool | None) -> None:
            if confirmed:
                db.delete_entry(self.conn, entry_id)
                self.refresh_status()
                self.refresh_entries()

        self.push_screen(ConfirmScreen(message), handle)

    def _edit_selected_time_entry(self) -> None:
        entry_id = self._selected_entry_id()
        if entry_id is None:
            return
        entry = db.get_entry(self.conn, entry_id)
        if entry is None:
            return

        def handle(result: tuple[str, str] | None) -> None:
            if result is None:
                return
            start_raw, end_raw = result
            now = datetime.now()
            try:
                start_dt = parse_time_input(start_raw, now) if start_raw else None
                end_dt = parse_time_input(end_raw, now) if end_raw else None
            except TimeParseError as e:
                self._show_error(str(e))
                return
            try:
                db.update_entry(self.conn, entry_id, start=start_dt, end=end_dt)
            except (db.EditError, db.OverlapError) as e:
                self._show_error(str(e))
                return
            self._show_error("")
            self.refresh_status()
            self.refresh_entries()

        self.push_screen(EditEntryScreen(entry), handle)

    # -- Projects tab -----------------------------------------------------

    def _refresh_projects_table(self, select_id: int | None = None) -> None:
        table = self.query_one("#projects-table", DataTable)
        table.clear()
        projects = db.list_projects(self.conn)
        select_row = None
        for idx, p in enumerate(projects):
            subtask_count = db.get_project_subtask_count(self.conn, p.id)
            table.add_row(str(p.id), p.name, p.case_number or "", str(subtask_count), key=str(p.id))
            if select_id is not None and p.id == select_id:
                select_row = idx
        if select_row is not None:
            table.move_cursor(row=select_row)
        self._refresh_subtasks_table()

    def _selected_project_row(self) -> db.Project | None:
        table = self.query_one("#projects-table", DataTable)
        if table.row_count == 0:
            return None
        row_key, _ = table.coordinate_to_cell_key(table.cursor_coordinate)
        if row_key.value is None:
            return None
        return db.get_project(self.conn, int(row_key.value))

    @on(DataTable.RowHighlighted, "#projects-table")
    def on_project_row_highlighted(self) -> None:
        self._refresh_subtasks_table()

    def _refresh_subtasks_table(self) -> None:
        table = self.query_one("#subtasks-table", DataTable)
        table.clear()
        project = self._selected_project_row()
        label = self.query_one("#subtasks-label", Label)
        if project is None:
            label.update("Subtasks")
            return
        label.update(f"Subtasks of '{project.name}'")
        for s in db.list_subtasks(self.conn, project.id):
            table.add_row(str(s.id), s.name, s.case_task or "", s.work_type or "", key=str(s.id))

    def _selected_subtask_row(self) -> db.Subtask | None:
        table = self.query_one("#subtasks-table", DataTable)
        if table.row_count == 0:
            return None
        row_key, _ = table.coordinate_to_cell_key(table.cursor_coordinate)
        if row_key.value is None:
            return None
        return db.get_subtask(self.conn, int(row_key.value))

    def _sync_timer_tab_after_project_changes(self) -> None:
        if self.selected_project is not None and db.get_project(self.conn, self.selected_project.id) is None:
            self.selected_project = None
            subtask_select = self.query_one("#subtask-select", Select)
            subtask_select.set_options([])
            subtask_select.disabled = True
            self.query_one("#start-btn", Button).disabled = True
        self.reload_projects()
        if self.selected_project is not None:
            self.reload_subtasks(self.selected_project.id)

    def _edit_selected_project(self) -> None:
        project = self._selected_project_row()
        if project is None:
            return

        def handle(updated: db.Project | None) -> None:
            if updated is not None:
                self._refresh_projects_table(select_id=updated.id)
                self._sync_timer_tab_after_project_changes()

        self.push_screen(EditProjectScreen(project), handle)

    def _delete_selected_project(self) -> None:
        project = self._selected_project_row()
        if project is None:
            return
        subtask_count = db.get_project_subtask_count(self.conn, project.id)
        entry_count = db.get_project_entry_count(self.conn, project.id)
        if subtask_count > 0:
            message = (
                f"Delete project '{project.name}', its {subtask_count} subtask(s), "
                f"and {entry_count} time entries?"
            )
        else:
            message = f"Delete project '{project.name}'?"

        def handle(confirmed: bool | None) -> None:
            if confirmed:
                db.delete_project(self.conn, project.id, force=True)
                self._refresh_projects_table()
                self._sync_timer_tab_after_project_changes()

        self.push_screen(ConfirmScreen(message), handle)

    def _edit_selected_subtask(self) -> None:
        subtask = self._selected_subtask_row()
        if subtask is None:
            return

        def handle(updated: db.Subtask | None) -> None:
            if updated is not None:
                self._refresh_subtasks_table()
                self._sync_timer_tab_after_project_changes()

        self.push_screen(EditSubtaskScreen(subtask), handle)

    def _new_subtask_for_selected_project(self) -> None:
        project = self._selected_project_row()
        if project is None:
            return

        def handle(created: db.Subtask | None) -> None:
            if created is not None:
                self._refresh_subtasks_table()
                self._sync_timer_tab_after_project_changes()

        self.push_screen(NewSubtaskScreen(project), handle)

    @on(Button.Pressed, "#new-project-btn")
    def on_new_project_btn(self) -> None:
        def handle(created: db.Project | None) -> None:
            if created is not None:
                self._refresh_projects_table(select_id=created.id)
                self._sync_timer_tab_after_project_changes()

        self.push_screen(NewProjectScreen(), handle)

    @on(Button.Pressed, "#edit-project-btn")
    def on_edit_project_btn(self) -> None:
        self._edit_selected_project()

    @on(Button.Pressed, "#delete-project-btn")
    def on_delete_project_btn(self) -> None:
        self._delete_selected_project()

    @on(Button.Pressed, "#new-subtask-btn")
    def on_new_subtask_btn(self) -> None:
        self._new_subtask_for_selected_project()

    @on(Button.Pressed, "#edit-subtask-btn")
    def on_edit_subtask_btn(self) -> None:
        self._edit_selected_subtask()

    # -- Week tab -----------------------------------------------------------

    def refresh_week_table(self) -> None:
        monday = self.week_monday
        sunday = monday + timedelta(days=6)
        report = db.get_week_report(self.conn, monday, sunday)
        days = [monday + timedelta(days=i) for i in range(7)]
        self._week_report_rows = report
        self._week_days = days

        table = self.query_one("#week-table", DataTable)
        table.clear(columns=True)
        table.add_columns(
            "Type", "Sagsnr.", "Sagsopgave", "Arbejdstype", "Beskrivelse",
            *(_day_header(d) for d in days),
        )
        for row in report:
            table.add_row(
                "Sag",
                row.sagsnr or "",
                row.sagsopgave or "",
                row.arbejdstype or "",
                row.beskrivelse,
                *(_format_hours(h) for h in row.hours_by_day),
            )

        week_no = monday.isocalendar()[1]
        label = self.query_one("#week-label", Static)
        label.update(f"Week {week_no}: {monday.isoformat()} – {sunday.isoformat()}")
        self.query_one("#week-error", Label).update("")

    @on(Button.Pressed, "#week-prev")
    def on_week_prev(self) -> None:
        self.week_monday -= timedelta(days=7)
        self.refresh_week_table()

    @on(Button.Pressed, "#week-next")
    def on_week_next(self) -> None:
        self.week_monday += timedelta(days=7)
        self.refresh_week_table()

    @on(Button.Pressed, "#week-this")
    def on_week_this(self) -> None:
        today = date.today()
        self.week_monday = today - timedelta(days=today.weekday())
        self.refresh_week_table()

    @on(Button.Pressed, "#week-copy")
    def on_week_copy(self) -> None:
        error = self.query_one("#week-error", Label)
        if not self._week_report_rows:
            error.update("Nothing to copy")
            return
        header = ["Type", "Sagsnr.", "Sagsopgave", "Arbejdstype", "Beskrivelse"] + [
            _day_header(d) for d in self._week_days
        ]
        lines = ["\t".join(header)]
        for row in self._week_report_rows:
            cells = [
                "Sag",
                row.sagsnr or "",
                row.sagsopgave or "",
                row.arbejdstype or "",
                row.beskrivelse,
            ] + [_format_hours(h) for h in row.hours_by_day]
            lines.append("\t".join(cells))
        try:
            _copy_to_clipboard("\n".join(lines[1:]))
            error.update("Copied to clipboard (header excluded)")
        except Exception as e:
            error.update(f"Could not copy to clipboard ({e})")

    # -- global actions -------------------------------------------------

    def action_delete_selected(self) -> None:
        tabs = self.query_one(TabbedContent)
        if tabs.active == "tab-timer":
            self._delete_selected_time_entry()
        elif tabs.active == "tab-projects":
            self._delete_selected_project()

    def action_edit_selected(self) -> None:
        tabs = self.query_one(TabbedContent)
        if tabs.active == "tab-timer":
            self._edit_selected_time_entry()
        elif tabs.active == "tab-projects":
            if self.focused is self.query_one("#subtasks-table"):
                self._edit_selected_subtask()
            else:
                self._edit_selected_project()

    def action_refresh_all(self) -> None:
        self.reload_projects()
        if self.selected_project is not None:
            self.reload_subtasks(self.selected_project.id)
        self.refresh_status()
        self.refresh_entries()
        self._refresh_projects_table()
        self.refresh_week_table()
        self._show_error("")


def main() -> None:
    TimeTrackerTUI().run()


if __name__ == "__main__":
    main()
