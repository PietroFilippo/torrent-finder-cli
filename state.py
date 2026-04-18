"""Persist engine toggles and active filter presets across runs."""

import json
import os

STATE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "filter_state.json")


def load_state(providers) -> None:
    """Apply saved engine/preset selections onto the given provider instances in place."""
    if not os.path.exists(STATE_PATH):
        return
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return

    provider_states = data.get("providers", {})
    for provider in providers:
        pstate = provider_states.get(provider.name)
        if not pstate:
            continue

        saved_engines = pstate.get("engines", {})
        for engine in provider.engines:
            if engine.name in saved_engines:
                engine.enabled = bool(saved_engines[engine.name])

        saved_preset_names = pstate.get("active_presets", [])
        provider.active_presets = [
            p for p in provider.presets if p.name in saved_preset_names
        ]


def save_state(providers) -> None:
    """Write current engine/preset selections to disk. Silent on failure."""
    data = {"providers": {}}
    for provider in providers:
        data["providers"][provider.name] = {
            "engines": {e.name: e.enabled for e in provider.engines},
            "active_presets": [p.name for p in provider.active_presets],
        }
    try:
        with open(STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except OSError:
        pass
