"""Typed registry for credentialed integrations and their verifiers.

The registry's text is English and marked with ``N_()``: a field's label, an
integration's category, limit, how-to and tip are translated where they are
drawn (``t(field.label)``), and ``display_name()``/``status_label()`` give the
name and the status in the interface language. ``name`` and ``status()`` stay
English: other screens compare them.
"""

# i18n: converted

from dataclasses import dataclass
from typing import Callable, Mapping

from torrent_finder.i18n import N_, t, tn


VerificationResult = tuple[bool | None, str]
CredentialVerifier = Callable[[Mapping[str, str | None]], VerificationResult]

# status() values, compared by other screens ("not set"), and what they read as.
STATUS_LABELS = {
    "not set": N_("not set", ctx="credential status"),
    "set via environment": N_("set via environment", ctx="credential status"),
    "saved": N_("saved", ctx="credential status"),
}


@dataclass(frozen=True)
class CredentialField:
    """One stored value in a credential entry; *label* is English, translated when drawn."""

    env_key: str
    label: str
    secret: bool = False
    required: bool = True

    @property
    def file_key(self) -> str:
        return self.env_key.lower()

    def display_label(self) -> str:
        """The field's label in the interface language."""
        return t(self.label)

    def value(self) -> str | None:
        from torrent_finder import credentials

        return credentials.get_credential(self.env_key)

    def source(self) -> str | None:
        from torrent_finder import credentials

        return credentials.credential_source(self.env_key)

    def env_override(self) -> bool:
        from torrent_finder import credentials

        return credentials.env_overrides(self.env_key)

    def stored_in_file(self) -> bool:
        from torrent_finder import credentials

        return credentials.file_has(self.env_key)


@dataclass(frozen=True)
class CredentialSpec:
    """Metadata and behavior for one credentialed integration."""

    id: str
    category: str
    icon: str
    name: str
    fields: tuple[CredentialField, ...]
    verifier: CredentialVerifier
    limit: str = ""
    howto: tuple[str, ...] = ()
    tip: str = ""

    @property
    def required_fields(self) -> tuple[CredentialField, ...]:
        return tuple(field for field in self.fields if field.required)

    def effective_values(self, entered: Mapping[str, str]) -> dict[str, str | None]:
        return {
            field.env_key: entered.get(field.env_key) or field.value()
            for field in self.fields
        }

    def missing_required(
        self, effective: Mapping[str, str | None]
    ) -> tuple[CredentialField, ...]:
        return tuple(
            field for field in self.required_fields
            if not effective.get(field.env_key)
        )

    def display_name(self) -> str:
        """The integration's name in the interface language: proper names stay, descriptions translate.

        ``name`` stays English: other screens match it against engine names.
        """
        if self.name in {"qBittorrent WebUI", "OpenSubtitles.com", "RuTracker", "Online-Fix"}:
            return self.name  # proper names, including in the pseudo-locale
        return t(self.name)

    def verify(self, effective: Mapping[str, str | None]) -> VerificationResult:
        missing = self.missing_required(effective)
        if missing:
            labels = ", ".join(field.display_label() for field in missing)
            # English keeps its "(s)"; a translation gives a singular and a plural.
            return False, tn("missing required field(s): {labels}", "missing required field(s): {labels}",
                             len(missing), labels=labels)
        return self.verifier(effective)

    def status(self) -> str:
        """``"not set"``, ``"set via environment"`` or ``"saved"``: English, compared by other screens.

        ``status_label()`` is the same in the interface language.
        """
        if not all(field.value() for field in self.required_fields):
            return "not set"  # i18n: ignore
        if any(field.source() == "env" for field in self.required_fields):
            return "set via environment"  # i18n: ignore
        return "saved"  # i18n: ignore

    def status_label(self) -> str:
        """``status()`` as the interface language says it, for drawing."""
        return t(STATUS_LABELS[self.status()])

    def has_any_credentials(self) -> bool:
        return any(
            field.stored_in_file() or field.env_override()
            for field in self.fields
        )

    def save(self, updates: Mapping[str, str]) -> None:
        from torrent_finder import credentials

        credentials.save_credentials(dict(updates))

    def clear_saved(self) -> None:
        from torrent_finder import credentials

        credentials.save_credentials({field.env_key: None for field in self.fields})

    def environment_override_keys(self) -> tuple[str, ...]:
        return tuple(
            field.env_key for field in self.fields if field.env_override()
        )


def _required_value(values: Mapping[str, str | None], key: str) -> str:
    value = values.get(key)
    if not value:
        # Never shown: verify() checks required fields first, and the form names only the error's type.
        raise ValueError(f"Missing required credential: {key}")  # i18n: ignore
    return value


def _verify_opensubtitles(values: Mapping[str, str | None]) -> VerificationResult:
    from torrent_finder.subtitles import test_opensubtitles

    return test_opensubtitles(
        _required_value(values, "OPENSUBTITLES_USERNAME"),
        _required_value(values, "OPENSUBTITLES_PASSWORD"),
        values.get("OPENSUBTITLES_APIKEY"),
    )


def _verify_addic7ed(values: Mapping[str, str | None]) -> VerificationResult:
    from torrent_finder.subtitles import test_addic7ed

    return test_addic7ed(
        _required_value(values, "ADDIC7ED_USERNAME"),
        _required_value(values, "ADDIC7ED_PASSWORD"),
    )


def _verify_jimaku(values: Mapping[str, str | None]) -> VerificationResult:
    from torrent_finder.jimaku import validate_key

    return validate_key(_required_value(values, "JIMAKU_API_KEY"))


def _verify_rutracker(values: Mapping[str, str | None]) -> VerificationResult:
    from torrent_finder import rutracker

    return rutracker.test_credentials(
        _required_value(values, "RUTRACKER_USERNAME"),
        _required_value(values, "RUTRACKER_PASSWORD"),
    )


def _verify_online_fix(values: Mapping[str, str | None]) -> VerificationResult:
    from torrent_finder import online_fix

    return online_fix.test_credentials(
        _required_value(values, "ONLINE_FIX_USERNAME"),
        _required_value(values, "ONLINE_FIX_PASSWORD"),
    )


def _verify_madokami(values: Mapping[str, str | None]) -> VerificationResult:
    from torrent_finder import madokami

    return madokami.test_credentials(
        _required_value(values, "MADOKAMI_USERNAME"),
        _required_value(values, "MADOKAMI_PASSWORD"),
    )


def _verify_tmdb(values: Mapping[str, str | None]) -> VerificationResult:
    from torrent_finder.resolvers import tmdb

    return tmdb.test_api_key(_required_value(values, "TMDB_API_KEY"))


def _verify_igdb(values: Mapping[str, str | None]) -> VerificationResult:
    from torrent_finder.resolvers import igdb

    return igdb.test_credentials(
        _required_value(values, "IGDB_CLIENT_ID"),
        _required_value(values, "IGDB_CLIENT_SECRET"),
    )


def _verify_qbittorrent(values: Mapping[str, str | None]) -> VerificationResult:
    from torrent_finder.qbittorrent import verify
    return verify(values)


CREDENTIAL_REGISTRY: tuple[CredentialSpec, ...] = (
    CredentialSpec(
        id="qbittorrent", category=N_("Torrent client"), icon="⬇",
        name="qBittorrent WebUI",  # i18n: ignore (a name)
        fields=(CredentialField("QBITTORRENT_URL", N_("WebUI URL (e.g. http://127.0.0.1:8080)")),
                CredentialField("QBITTORRENT_USERNAME", N_("WebUI username (optional for trusted access)"),
                                required=False),
                CredentialField("QBITTORRENT_PASSWORD", N_("WebUI password"), secret=True, required=False)),
        verifier=_verify_qbittorrent,
        howto=(N_("Enable WebUI in qBittorrent's settings and enter its address here."),
               N_("For a remote client, use its configured HTTPS endpoint. Save paths belong to that computer.")),
        tip=N_("This app does not change WebUI exposure or authentication settings."),
    ),
    CredentialSpec(
        id="opensubtitles",
        category=N_("Subtitles"),
        icon="🎬",
        name="OpenSubtitles.com",  # i18n: ignore (a name)
        fields=(
            CredentialField("OPENSUBTITLES_USERNAME", N_("Username")),
            CredentialField("OPENSUBTITLES_PASSWORD", N_("Password"), secret=True),
            CredentialField(
                "OPENSUBTITLES_APIKEY",
                N_("API key (optional, blank to skip)"),
                secret=True,
                required=False,
            ),
        ),
        verifier=_verify_opensubtitles,
        limit=N_("Free accounts have a small daily download limit; VIP raises it."),
    ),
    CredentialSpec(
        id="addic7ed",
        category=N_("Subtitles"),
        icon="📺",
        name=N_("Addic7ed (TV series)"),
        fields=(
            CredentialField("ADDIC7ED_USERNAME", N_("Username")),
            CredentialField("ADDIC7ED_PASSWORD", N_("Password"), secret=True),
        ),
        verifier=_verify_addic7ed,
        limit=N_("Limits downloads per day (more with an account than anonymous)."),
    ),
    CredentialSpec(
        id="jimaku",
        category=N_("Subtitles"),
        icon="🍙",
        name=N_("Jimaku (anime)"),
        fields=(CredentialField("JIMAKU_API_KEY", N_("API key"), secret=True),),
        verifier=_verify_jimaku,
    ),
    CredentialSpec(
        id="rutracker",
        category=N_("Search provider logins"),
        icon="🧲",
        name="RuTracker",  # i18n: ignore (a name)
        fields=(
            CredentialField("RUTRACKER_USERNAME", N_("Username")),
            CredentialField("RUTRACKER_PASSWORD", N_("Password"), secret=True),
        ),
        verifier=_verify_rutracker,
        limit=N_(
            "Required — the RuTracker provider logs in to search and returns "
            "nothing without an account."
        ),
    ),
    CredentialSpec(
        id="online_fix",
        category=N_("Search provider logins"),
        icon="🔧",
        name="Online-Fix",  # i18n: ignore (a name)
        fields=(
            CredentialField("ONLINE_FIX_USERNAME", N_("Username")),
            CredentialField("ONLINE_FIX_PASSWORD", N_("Password"), secret=True),
        ),
        verifier=_verify_online_fix,
        limit=N_(
            "Optional — Online-Fix search and download work without it; login "
            "is supported for completeness."
        ),
    ),
    CredentialSpec(
        id="madokami",
        category=N_("Search provider logins"),
        icon="📕",
        name=N_("Madokami (manga)"),
        fields=(
            CredentialField("MADOKAMI_USERNAME", N_("Username")),
            CredentialField("MADOKAMI_PASSWORD", N_("Password"), secret=True),
        ),
        verifier=_verify_madokami,
        limit=N_(
            "Required — the Madokami provider authenticates every request and "
            "returns nothing without an account."
        ),
    ),
    CredentialSpec(
        id="tmdb",
        category=N_("Creator-search upgrades (optional)"),
        icon="🎬",
        name=N_("TMDB (Movies & Series — by director / studio)"),
        fields=(CredentialField("TMDB_API_KEY", N_("API key (v3)"), secret=True),),
        verifier=_verify_tmdb,
        limit=N_(
            "Optional — Movies & Series 'by director / studio' works keyless via "
            "Wikidata; a free TMDB v3 API key upgrades it to richer results."
        ),
        howto=(
            N_("Create a free account at themoviedb.org"),
            N_("Settings → API → Request an API key (choose Developer, accept the terms)"),
            N_("Copy the “API Key (v3 auth)” and paste it below"),
        ),
        tip=N_("The form's Application URL can be anything valid — e.g. http://localhost"),
    ),
    CredentialSpec(
        id="igdb",
        category=N_("Creator-search upgrades (optional)"),
        icon="🎮",
        name=N_("IGDB (Games — by developer / publisher)"),
        fields=(
            CredentialField("IGDB_CLIENT_ID", N_("Twitch Client ID")),
            CredentialField("IGDB_CLIENT_SECRET", N_("Twitch Client Secret"), secret=True),
        ),
        verifier=_verify_igdb,
        limit=N_(
            "Optional — Games 'by developer / publisher' works keyless via "
            "Wikidata; free Twitch/IGDB creds (dev.twitch.tv → register an app) "
            "upgrade it to richer results."
        ),
        howto=(  # Twitch's console is in English: its button and field names stay as it shows them
            N_("dev.twitch.tv/console → Applications → Register Your Application"),
            N_("OAuth Redirect URL: http://localhost  •  Category: Application Integration"),
            N_("Copy the Client ID, click New Secret, copy the Client Secret → paste below"),
        ),
        tip=N_("The Client Secret is shown only once — copy it before leaving the page"),
    ),
)


def _build_credential_index() -> dict[str, CredentialSpec]:
    index: dict[str, CredentialSpec] = {}
    field_owners: dict[str, str] = {}
    for spec in CREDENTIAL_REGISTRY:  # a mistake in the registry above stops the import: for developers
        if spec.id in index:
            raise ValueError(f"Duplicate credential id: {spec.id!r}")  # i18n: ignore
        index[spec.id] = spec
        for field in spec.fields:
            owner = field_owners.get(field.env_key)
            if owner:
                raise ValueError(
                    f"Credential field {field.env_key!r} belongs to both "  # i18n: ignore
                    f"{owner!r} and {spec.id!r}"
                )
            field_owners[field.env_key] = spec.id
    return index


_CREDENTIALS_BY_ID = _build_credential_index()


def get_credential_spec(credential_id: str) -> CredentialSpec | None:
    """Return a registry entry by its stable id."""
    return _CREDENTIALS_BY_ID.get(credential_id)


def credential_file_keys() -> dict[str, str]:
    """Return env-to-file key mappings derived from registered fields."""
    return {
        field.env_key: field.file_key
        for spec in CREDENTIAL_REGISTRY
        for field in spec.fields
    }
