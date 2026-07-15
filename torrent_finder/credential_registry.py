"""Typed registry for credentialed integrations and their verifiers."""

from dataclasses import dataclass
from typing import Callable, Mapping


VerificationResult = tuple[bool | None, str]
CredentialVerifier = Callable[[Mapping[str, str | None]], VerificationResult]


@dataclass(frozen=True)
class CredentialField:
    """One stored value in a credential entry."""

    env_key: str
    label: str
    secret: bool = False
    required: bool = True

    @property
    def file_key(self) -> str:
        return self.env_key.lower()

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

    def verify(self, effective: Mapping[str, str | None]) -> VerificationResult:
        missing = self.missing_required(effective)
        if missing:
            labels = ", ".join(field.label for field in missing)
            return False, f"missing required field(s): {labels}"
        return self.verifier(effective)

    def status(self) -> str:
        if not all(field.value() for field in self.required_fields):
            return "not set"
        if any(field.source() == "env" for field in self.required_fields):
            return "set via environment"
        return "saved"

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
        raise ValueError(f"Missing required credential: {key}")
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


CREDENTIAL_REGISTRY: tuple[CredentialSpec, ...] = (
    CredentialSpec(
        id="opensubtitles",
        category="Subtitles",
        icon="🎬",
        name="OpenSubtitles.com",
        fields=(
            CredentialField("OPENSUBTITLES_USERNAME", "Username"),
            CredentialField("OPENSUBTITLES_PASSWORD", "Password", secret=True),
            CredentialField(
                "OPENSUBTITLES_APIKEY",
                "API key (optional, blank to skip)",
                secret=True,
                required=False,
            ),
        ),
        verifier=_verify_opensubtitles,
        limit="Free accounts have a small daily download limit; VIP raises it.",
    ),
    CredentialSpec(
        id="addic7ed",
        category="Subtitles",
        icon="📺",
        name="Addic7ed (TV series)",
        fields=(
            CredentialField("ADDIC7ED_USERNAME", "Username"),
            CredentialField("ADDIC7ED_PASSWORD", "Password", secret=True),
        ),
        verifier=_verify_addic7ed,
        limit="Limits downloads per day (more with an account than anonymous).",
    ),
    CredentialSpec(
        id="jimaku",
        category="Subtitles",
        icon="🍙",
        name="Jimaku (anime)",
        fields=(CredentialField("JIMAKU_API_KEY", "API key", secret=True),),
        verifier=_verify_jimaku,
    ),
    CredentialSpec(
        id="rutracker",
        category="Search provider logins",
        icon="🧲",
        name="RuTracker",
        fields=(
            CredentialField("RUTRACKER_USERNAME", "Username"),
            CredentialField("RUTRACKER_PASSWORD", "Password", secret=True),
        ),
        verifier=_verify_rutracker,
        limit=(
            "Required — the RuTracker provider logs in to search and returns "
            "nothing without an account."
        ),
    ),
    CredentialSpec(
        id="online_fix",
        category="Search provider logins",
        icon="🔧",
        name="Online-Fix",
        fields=(
            CredentialField("ONLINE_FIX_USERNAME", "Username"),
            CredentialField("ONLINE_FIX_PASSWORD", "Password", secret=True),
        ),
        verifier=_verify_online_fix,
        limit=(
            "Optional — Online-Fix search and download work without it; login "
            "is supported for completeness."
        ),
    ),
    CredentialSpec(
        id="madokami",
        category="Search provider logins",
        icon="📕",
        name="Madokami (manga)",
        fields=(
            CredentialField("MADOKAMI_USERNAME", "Username"),
            CredentialField("MADOKAMI_PASSWORD", "Password", secret=True),
        ),
        verifier=_verify_madokami,
        limit=(
            "Required — the Madokami provider authenticates every request and "
            "returns nothing without an account."
        ),
    ),
    CredentialSpec(
        id="tmdb",
        category="Creator-search upgrades (optional)",
        icon="🎬",
        name="TMDB (Movies & Series — by director / studio)",
        fields=(CredentialField("TMDB_API_KEY", "API key (v3)", secret=True),),
        verifier=_verify_tmdb,
        limit=(
            "Optional — Movies & Series 'by director / studio' works keyless via "
            "Wikidata; a free TMDB v3 API key upgrades it to richer results."
        ),
        howto=(
            "Create a free account at themoviedb.org",
            "Settings → API → Request an API key (choose Developer, accept the terms)",
            "Copy the “API Key (v3 auth)” and paste it below",
        ),
        tip="The form's Application URL can be anything valid — e.g. http://localhost",
    ),
    CredentialSpec(
        id="igdb",
        category="Creator-search upgrades (optional)",
        icon="🎮",
        name="IGDB (Games — by developer / publisher)",
        fields=(
            CredentialField("IGDB_CLIENT_ID", "Twitch Client ID"),
            CredentialField("IGDB_CLIENT_SECRET", "Twitch Client Secret", secret=True),
        ),
        verifier=_verify_igdb,
        limit=(
            "Optional — Games 'by developer / publisher' works keyless via "
            "Wikidata; free Twitch/IGDB creds (dev.twitch.tv → register an app) "
            "upgrade it to richer results."
        ),
        howto=(
            "dev.twitch.tv/console → Applications → Register Your Application",
            "OAuth Redirect URL: http://localhost  •  Category: Application Integration",
            "Copy the Client ID, click New Secret, copy the Client Secret → paste below",
        ),
        tip="The Client Secret is shown only once — copy it before leaving the page",
    ),
)


def _build_credential_index() -> dict[str, CredentialSpec]:
    index: dict[str, CredentialSpec] = {}
    field_owners: dict[str, str] = {}
    for spec in CREDENTIAL_REGISTRY:
        if spec.id in index:
            raise ValueError(f"Duplicate credential id: {spec.id!r}")
        index[spec.id] = spec
        for field in spec.fields:
            owner = field_owners.get(field.env_key)
            if owner:
                raise ValueError(
                    f"Credential field {field.env_key!r} belongs to both "
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
