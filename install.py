"""Run with Python 3.10+ from a stable clone. Registers local tools, no remote service."""
import json
from pathlib import Path
import shutil
import subprocess
import sys


def main():
    if sys.version_info < (3, 10):
        raise SystemExit("Python 3.10 or newer is required")
    root = Path(__file__).resolve().parent
    codex = shutil.which("codex.cmd") if sys.platform == "win32" else shutil.which("codex")
    if not codex:
        raise SystemExit("Codex CLI was not found. Install/sign in to Codex CLI first, then rerun this script.")
    catalog = json.loads((root / ".agents/plugins/marketplace.json").read_text(encoding="utf-8"))
    commands = [
        [codex, "plugin", "marketplace", "add", str(root)],
        [codex, "plugin", "add", "project-coding-harness@" + catalog["name"]],
    ]
    print("Installing the plugin with its bundled local MCP server.")
    for command in commands:
        subprocess.run(command, check=True)
    print("Installed. Restart the app and start a new task in YOUR project. Ask: Project Coding Harness 설정 화면을 열어줘")


if __name__ == "__main__":
    main()
