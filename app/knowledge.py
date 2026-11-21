import json
from functools import lru_cache
from pathlib import Path
from typing import Any


@lru_cache(maxsize=1)
def load_knowledge() -> dict[str, Any]:
    data_path = Path(__file__).parent / "data" / "migration.json"
    with data_path.open(encoding="utf-8") as migration_file:
        return json.load(migration_file)


@lru_cache(maxsize=1)
def load_employee_history() -> dict[str, Any]:
    data_path = Path(__file__).parent / "data" / "employee_history.json"
    with data_path.open(encoding="utf-8") as history_file:
        return json.load(history_file)


def get_roles() -> list[dict[str, Any]]:
    return load_knowledge()["roles"]


def get_role(role_id: str) -> dict[str, Any] | None:
    return next((role for role in get_roles() if role["id"] == role_id), None)


def get_migration_notes() -> list[dict[str, Any]]:
    return load_knowledge()["notes"]


def get_sources() -> list[dict[str, Any]]:
    return load_knowledge()["sources"]


def get_software_history(role_id: str) -> list[dict[str, Any]]:
    return load_employee_history().get("histories", {}).get(role_id, [])