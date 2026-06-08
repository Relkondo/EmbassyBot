from __future__ import annotations

import logging
import re
from pathlib import Path


LOGGER = logging.getLogger(__name__)
def persist_tokens_to_config(
    config_path: str,
    authorization_token: str,
) -> None:
    path = Path(config_path)
    text = path.read_text(encoding="utf-8")
    replacements = {
        "AUTHORIZATION_TOKEN": authorization_token,
    }

    for name, value in replacements.items():
        assignment = f'{name} = {value!r}'
        pattern = re.compile(rf"^{name}\s*=.*$", re.MULTILINE)
        if pattern.search(text):
            text = pattern.sub(assignment, text, count=1)
        else:
            text = f"{text.rstrip()}\n{name} = {value!r}\n"

    text = re.sub(r"^REFRESH_TOKEN\s*=.*\n?", "", text, flags=re.MULTILINE)

    tmp_path = path.with_suffix(f"{path.suffix}.tmp")
    tmp_path.write_text(text, encoding="utf-8")
    tmp_path.replace(path)
    LOGGER.info("Persisted fresh authorization tokens to %s", path)
