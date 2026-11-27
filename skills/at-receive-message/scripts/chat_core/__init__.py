"""Project-local messaging, shared by the MCP, CLI and visualizer."""
from pathlib import Path
import sys

# Source checkouts and installations have the same sibling skill layout.
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "at-init-team/scripts"))
