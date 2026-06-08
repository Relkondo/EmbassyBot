from __future__ import annotations

from pathlib import Path
from types import ModuleType


def load_optional_config_text(
    config_module: ModuleType,
    inline_name: str,
    file_name: str,
) -> str:
    file_value = getattr(config_module, file_name, "")
    if file_value not in {None, ""}:
        if not isinstance(file_value, str):
            raise ValueError(f"{file_name} must be a string path")
        path = Path(file_value)
        if not path.is_absolute():
            path = Path(config_module.__file__).resolve().parent / path
        return path.read_text(encoding="utf-8").strip()

    inline_value = getattr(config_module, inline_name, "")
    if inline_value in {None, ""}:
        return ""
    if not isinstance(inline_value, str):
        raise ValueError(f"{inline_name} must be a string")
    return inline_value.strip()
