import os
import sys
import warnings
from pathlib import Path
import pytest

# Suppress ResourceWarnings for unclosed sqlite3 connections (JobManager closes them; warnings appear during GC)
warnings.filterwarnings("ignore", category=ResourceWarning)

# Use a single file-based test DB so all connections share the same schema.
# (:memory: would create a new DB per connection, so "no such table" after _init_db.)
_tests_dir = Path(__file__).resolve().parent
_test_db_path = _tests_dir / "test_jobs.db"
# Force test DB path so tests always use it (override any .env or system API__DB_PATH)
os.environ["API__DB_PATH"] = str(_test_db_path)

# Ensure project root is on the import path
sys.path.insert(0, str(_tests_dir.parent))


@pytest.fixture
def flask_client():
    """Provide a Flask test client with the app in testing mode."""
    from app import create_app
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client
