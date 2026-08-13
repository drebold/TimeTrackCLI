import pytest

from time_tracker_app import db


@pytest.fixture
def conn(tmp_path):
    db_path = tmp_path / "test.db"
    connection = db.get_connection(db_path)
    yield connection
    connection.close()


@pytest.fixture
def cli_env(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("TT_DB_PATH", str(db_path))
    return db_path
