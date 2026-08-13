from dataclasses import dataclass


@dataclass
class Project:
    id: int
    name: str


@dataclass
class Subtask:
    id: int
    project_id: int
    name: str
    case_task: str | None = None  # Sagsopgave
    work_type: str | None = None  # Arbejdstype


@dataclass
class TimeEntry:
    id: int
    subtask_id: int
    started_at: str  # ISO 8601, e.g. "2026-08-13T09:00:00"
    ended_at: str | None  # None while running


@dataclass
class TimeEntryView:
    id: int
    project_name: str
    subtask_name: str
    started_at: str
    ended_at: str | None


@dataclass
class WeekReportRow:
    sagsnr: str  # project name
    sagsopgave: str | None
    arbejdstype: str | None
    beskrivelse: str  # subtask name
    hours_by_day: list[float]  # 7 entries, Monday..Sunday
