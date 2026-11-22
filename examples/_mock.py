"""Switch between offline mock responses and real provider calls."""
import os

LIVE = os.environ.get("LIVE") == "1"


def mock(text):
    """Return completion kwargs that fake the reply unless LIVE=1."""
    return {} if LIVE else {"mock_response": text}
