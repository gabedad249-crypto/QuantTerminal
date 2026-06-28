from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REQUIRED_DIRS = [
    "config", "database", "logs", "cache", "screenshots",
    "exports", "docs", "assets", "themes", "tests"
]

def ensure_project_dirs() -> None:
    for folder in REQUIRED_DIRS:
        (ROOT / folder).mkdir(parents=True, exist_ok=True)
