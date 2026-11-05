import json
from pathlib import Path

from app.routes import ROUTES


def load_settings(path="settings.json"):
    file = Path(path)
    if not file.exists():
        return {"debug": False, "port": 8000}
    return json.loads(file.read_text())


def handle(path, settings):
    handler = ROUTES.get(path)
    if handler is None:
        return 404, "Not found"
    return 200, handler(settings)
