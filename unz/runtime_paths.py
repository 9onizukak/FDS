"""Keep installed app data writable and credentials outside the executable."""
import os
from pathlib import Path
import shutil
import sys

RESOURCE_DIR = Path(__file__).resolve().parent


def ensure_config(path, template):
    """Add new default variables on upgrade without replacing existing values."""
    if not path.exists():
        shutil.copyfile(template, path)
        return
    existing = path.read_text(encoding="utf-8")
    keys = {line.split("=", 1)[0].strip() for line in existing.splitlines()
            if "=" in line and not line.lstrip().startswith("#")}
    missing = [line for line in template.read_text(encoding="utf-8").splitlines()
               if "=" in line and not line.lstrip().startswith("#")
               and line.split("=", 1)[0].strip() not in keys]
    if missing:
        with path.open("a", encoding="utf-8") as config:
            config.write("\n# New default variables\n" + "\n".join(missing) + "\n")


if getattr(sys, "frozen", False):
    DATA_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "FDH"
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    ensure_config(DATA_DIR / ".env", RESOURCE_DIR / ".env.example")
else:
    DATA_DIR = RESOURCE_DIR

ENV_PATH = DATA_DIR / ".env"
HISTORY_PATH = DATA_DIR / "send_history.jsonl"
