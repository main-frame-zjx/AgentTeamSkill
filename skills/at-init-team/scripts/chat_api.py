"""Load the sibling communication skill from either checkout or installed layout."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "at-receive-message/scripts"))
from chat_core.store import directory, initialize
from chat_core.engine import run as chat_run
from chat_core.tasks_bridge import notification, snapshot
