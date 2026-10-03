"""Named search configurations, edited in memory and committed together.

IDs survive renaming. A profile contains a combined-provider snapshot, never
provider instances or credentials. The legacy combined configuration remains
available until the first explicit save, which materializes it as Default.
"""

from copy import deepcopy
import unicodedata
from uuid import uuid4

from torrent_finder import store
from torrent_finder.state import load_setting, save_setting


class ProfileError(ValueError):
    """User-facing validation failure; preserve the saved collection."""


class ProfileLibrary:
    def __init__(self, data):
        self.data = deepcopy(data)
        if not isinstance(self.data, dict) or self.data.get("version") != 1:
            raise ProfileError("Unsupported search profile data; saved profiles were not changed.")
        entries = self.data.get("profiles")
        if not isinstance(entries, list) or not entries:
            raise ProfileError("Search profile data has no profiles; saved data was not changed.")
        ids, names = set(), set()
        for entry in entries:
            if not isinstance(entry, dict):
                raise ProfileError("Invalid search profile; saved data was not changed.")
            identity, name = entry.get("id"), entry.get("name")
            if (not isinstance(identity, str) or not identity or identity in ids
                    or not isinstance(name, str) or not name.strip() or name != name.strip()
                    or len(name) > 60 or any(unicodedata.category(c).startswith("C") for c in name)
                    or name.casefold() in names or not isinstance(entry.get("settings"), dict)):
                raise ProfileError("Invalid or duplicate search profile; saved data was not changed.")
            ids.add(identity)
            names.add(name.casefold())
        if not isinstance(self.data.get("active"), str) or self.data["active"] not in ids:
            raise ProfileError("The active search profile is missing; saved data was not changed.")

    @classmethod
    def load(cls):
        saved = load_setting("search_profiles")
        if saved is None:
            legacy = load_setting("combined_search", {})
            saved = {"version": 1, "active": "default", "profiles": [
                {"id": "default", "name": "Default", "settings": legacy if isinstance(legacy, dict) else {}}
            ]}
        return cls(saved)

    @property
    def entries(self):
        return self.data["profiles"]

    @property
    def current(self):
        return self.get(self.data["active"])

    def get(self, identity):
        return next(entry for entry in self.entries if entry["id"] == identity)

    def find(self, name):
        return next((entry for entry in self.entries if entry["name"].casefold() == name.strip().casefold()), None)

    def validate_name(self, name, identity=None):
        name = name.strip()
        if not name or len(name) > 60 or any(unicodedata.category(c).startswith("C") for c in name):
            raise ProfileError("Use a profile name of 1–60 characters, without control characters.")
        if any(entry["id"] != identity and entry["name"].casefold() == name.casefold() for entry in self.entries):
            raise ProfileError("A profile with that name already exists.")
        return name

    def create(self, name, settings):
        name = self.validate_name(name)
        entry = {"id": uuid4().hex, "name": name, "settings": deepcopy(settings)}
        self.entries.append(entry)
        self.select(entry["id"])
        return entry

    def rename(self, identity, name):
        self.get(identity)["name"] = self.validate_name(name, identity)

    def select(self, identity):
        self.get(identity)  # validate before changing the active ID
        self.data["active"] = identity

    def update(self, settings):
        self.current["settings"] = deepcopy(settings)

    def delete(self, identity):
        if len(self.entries) == 1:
            raise ProfileError("Keep at least one search profile.")
        entry = self.get(identity)
        self.entries.remove(entry)
        if self.data["active"] == identity:
            self.select(self.entries[0]["id"])

    def save(self):
        # Validate every draft, including a profile edited before switching.
        for entry in self.entries:
            if entry["settings"].get("selected") == []:
                raise ProfileError(f"Choose at least one provider for {entry['name']} before saving.")
        save_setting("search_profiles", deepcopy(self.data))
        # Keep the single-profile representation usable by previous versions.
        save_setting("combined_search", deepcopy(self.current["settings"]))
        store.flush()
