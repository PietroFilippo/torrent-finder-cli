"""IGDB resolver — Games developer + publisher lookups (the quality upgrade).

Used when Twitch/IGDB credentials are configured (`IGDB_CLIENT_ID` +
`IGDB_CLIENT_SECRET`); `resolvers/games.py` falls back to keyless Wikidata
otherwise. IGDB needs a Twitch app: register at dev.twitch.tv → use the Client
ID/Secret here. Auth is a Twitch app access token (cached, ~60-day life); queries
are POSTed in IGDB's apicalypse language.

Developer vs publisher are kept separate via the `involved_companies` table's
`developer` / `publisher` booleans (a company can be both, on different games),
which a plain `/games` filter can't distinguish.
"""

import time

import requests

import credentials
from resolvers.types import Entity, Work

_OAUTH = "https://id.twitch.tv/oauth2/token"
_API = "https://api.igdb.com/v4"
_LIMIT = 500  # IGDB's max page size
_token_cache = {"token": None, "exp": 0.0, "cid": None}


def _esc(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def _get_token(client_id: str | None = None, client_secret: str | None = None) -> str | None:
    """Twitch app access token, cached until ~1 min before expiry."""
    cid = client_id or credentials.get_credential("IGDB_CLIENT_ID")
    csec = client_secret or credentials.get_credential("IGDB_CLIENT_SECRET")
    if not cid or not csec:
        return None
    now = time.time()
    if _token_cache["token"] and _token_cache["cid"] == cid and now < _token_cache["exp"]:
        return _token_cache["token"]
    try:
        resp = requests.post(_OAUTH, params={
            "client_id": cid, "client_secret": csec, "grant_type": "client_credentials",
        }, timeout=12)
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError):
        return None
    tok = data.get("access_token")
    if not tok:
        return None
    _token_cache.update(token=tok, cid=cid, exp=now + max(0, int(data.get("expires_in", 0))) - 60)
    return tok


def _post(endpoint: str, body: str, _retry: bool = True) -> list | None:
    """POST an apicalypse query; return the JSON list or None on failure."""
    cid = credentials.get_credential("IGDB_CLIENT_ID")
    tok = _get_token()
    if not cid or not tok:
        return None
    try:
        resp = requests.post(
            f"{_API}/{endpoint}", data=body.encode("utf-8"),
            headers={"Client-ID": cid, "Authorization": f"Bearer {tok}", "Accept": "application/json"},
            timeout=12,
        )
        if resp.status_code == 401 and _retry:  # token went stale — refresh once
            _token_cache["token"] = None
            return _post(endpoint, body, _retry=False)
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError):
        return None
    return data if isinstance(data, list) else None


def company_search(name: str) -> "list[Entity] | None":
    """Resolve a company name to candidates. None when IGDB is unreachable.

    IGDB's `search` clause returns nothing on /companies, so match the name with
    a case-insensitive ``where name ~ *"…"*`` and rank client-side (exact, then
    prefix, then shortest) since `where` has no relevance ordering.
    """
    data = _post("companies", f'fields id,name; where name ~ *"{_esc(name)}"*; limit 50;')
    if data is None:
        return None
    low = name.lower()

    def _rank(c):
        n = (c.get("name") or "").lower()
        return (0 if n == low else 1 if n.startswith(low) else 2, len(n))

    data.sort(key=_rank)
    out: list[Entity] = []
    for c in data[:10]:
        cid = c.get("id")
        if cid is None:
            continue
        out.append(Entity(id=str(cid), name=c.get("name") or "Unknown", detail="Game company"))
    return out


def _company_games(entity: Entity, role: str) -> "tuple[list[Work], bool]":
    """Games where the company holds ``role`` (developer/publisher) — two-step via
    involved_companies so the role boolean is checked on the same record."""
    inv = _post("involved_companies",
                f"fields game; where company = {int(entity.id)} & {role} = true; limit {_LIMIT};")
    if inv is None:
        return [], False
    ids = list(dict.fromkeys(r.get("game") for r in inv if r.get("game")))
    if not ids:
        return [], False
    ids_csv = ",".join(str(i) for i in ids[:_LIMIT])
    games = _post("games",
                  f"fields name,first_release_date; where id = ({ids_csv}); "
                  f"sort total_rating_count desc; limit {_LIMIT};")
    if games is None:
        return [], False
    works: list[Work] = []
    for g in games:
        name = g.get("name")
        if not name:
            continue
        ts = g.get("first_release_date")
        year = time.gmtime(ts).tm_year if ts else None
        works.append(Work(title=name, alt_titles=(), year=year, subtitle=str(year) if year else ""))
    return works, False


def developer_works(entity: Entity, page: int = 1) -> "tuple[list[Work], bool]":
    if page != 1:
        return [], False
    return _company_games(entity, "developer")


def publisher_works(entity: Entity, page: int = 1) -> "tuple[list[Work], bool]":
    if page != 1:
        return [], False
    return _company_games(entity, "publisher")


def test_credentials(client_id: str, client_secret: str) -> "tuple[bool | None, str]":
    """Validate Twitch/IGDB creds: get a token, then a trivial IGDB query."""
    tok = _get_token(client_id, client_secret)
    if not tok:
        return False, "couldn't get a Twitch token — check Client ID and Secret"
    try:
        resp = requests.post(f"{_API}/games", data=b"fields id; limit 1;", headers={
            "Client-ID": client_id, "Authorization": f"Bearer {tok}", "Accept": "application/json",
        }, timeout=10)
    except requests.RequestException as exc:
        return None, f"couldn't reach IGDB ({exc})"
    if resp.status_code == 200:
        return True, "IGDB credentials valid"
    if resp.status_code in (401, 403):
        return False, "rejected by IGDB (Client-ID / token mismatch)"
    return None, f"unexpected response ({resp.status_code})"
