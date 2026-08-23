import importlib.resources
import shutil
from pathlib import Path

# NOTE: server is imported lazily inside main() (NOT at module top) so that an
# entrypoint like readonly.py can set PYSTXM_MCP_READONLY *before* server.py is
# imported and its READONLY flag is evaluated.


def _install_skills():
    dest = Path.home() / ".config" / "agents" / "skills"
    dest.mkdir(parents=True, exist_ok=True)
    skills_pkg = importlib.resources.files("pystxmcontrol.mcp") / "skills"
    for skill in skills_pkg.iterdir():
        target = dest / skill.name
        if not target.exists():
            shutil.copy2(skill, target)
            print(f"Installed skill: {target}")


def main():
    """
    Run pystxmcontrol mcp server
    """
    _install_skills()
    from .server import mcp   # lazy: honour PYSTXM_MCP_READONLY set before this
    mcp.run()

if __name__ == "__main__":
    main()