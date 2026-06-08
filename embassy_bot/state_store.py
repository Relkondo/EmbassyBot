from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


LOGGER = logging.getLogger(__name__)
DEFAULT_STATE_FILE = "embassy_bot_state.json"


@dataclass
class PollState:
    announced_start_times: set[datetime] = field(default_factory=set)
    failed_call_names: set[str] = field(default_factory=set)
    appointment_context: object | None = None


def load_poll_state(path: str | Path) -> PollState:
    state_path = Path(path)
    if not state_path.exists():
        return PollState()

    try:
        payload = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        LOGGER.exception("Failed to load poll state from %s", state_path)
        return PollState()

    start_times = set()
    values = payload.get("announced_start_times") if isinstance(payload, dict) else None
    if isinstance(values, list):
        for value in values:
            if not isinstance(value, str):
                continue
            try:
                start_times.add(datetime.fromisoformat(value))
            except ValueError:
                LOGGER.warning("Ignoring invalid persisted appointment datetime: %s", value)

    return PollState(announced_start_times=start_times)


def save_poll_state(path: str | Path, state: PollState) -> None:
    state_path = Path(path)
    payload = {
        "announced_start_times": [
            start_time.isoformat()
            for start_time in sorted(state.announced_start_times)
        ],
    }
    state_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = state_path.with_suffix(f"{state_path.suffix}.tmp")
    tmp_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    tmp_path.replace(state_path)
    LOGGER.info("Persisted poll state to %s", state_path)
