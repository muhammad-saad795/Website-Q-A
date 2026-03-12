import sys
from pathlib import Path
import pytest

# Ensure project root is on the import path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture
def flask_client():
    """Provide a Flask test client with the app in testing mode."""
    from app import create_app
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client
