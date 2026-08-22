from .server import mcp
import importlib.resources
import shutil
from pathlib import Path


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
    mcp.run()

if __name__ == "__main__":
    main()