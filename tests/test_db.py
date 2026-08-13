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
