"""Network exposure warning shown at startup."""

import os
import sys

import readchar
import requests
from rich.console import Group
from rich.text import Text

from torrent_finder.constants import console
from torrent_finder.state import load_setting, save_setting
from torrent_finder.ui import theme
from torrent_finder.ui.selector import _render

DISMISSED_KEY = "security_warning_dismissed"

# Substring tokens suggesting a VPN/proxy in the ipinfo `org` field.
VPN_ORG_HINTS = (
    "vpn", "mullvad", "proton", "nordvpn", "nord ",
    "private internet access", "ipvanish", "expressvpn",
    "surfshark", "windscribe", "airvpn", "pia ", "azire",
    "cyberghost", "perfect privacy", "ivpn", "tunnelbear",
    "torguard", "purevpn", "hide.me", "m247", "datacamp",
)


def _fetch_network_info(timeout: float = 3.0) -> dict | None:
    """Query ip-api.com for public IP + proxy/hosting flags. None on failure.

    Free endpoint is HTTP only; response is plaintext but only used locally.
    """
    try:
        resp = requests.get(
            "http://ip-api.com/json/",
            params={"fields": "status,country,city,isp,org,as,asname,proxy,hosting,mobile,query"},
            timeout=timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") != "success":
            return None
        return data
    except Exception:
        return None


def _looks_like_vpn(org: str) -> bool:
    org_l = org.lower()
    return any(token in org_l for token in VPN_ORG_HINTS)


def show_security_warning(force: bool = False) -> bool:
    """Show network-exposure panel and wait for acknowledgement.

    Returns False only if the user aborts with Esc/Ctrl-C. Returns True on
    Enter, on `D` (permanently dismiss), when bypassed via the
    TORRENT_SKIP_WARNING env var, or when previously dismissed.

    Pass force=True to bypass the env var and the dismissed flag (used by
    the provider selector's "Network exposure info" action).
    """
    if not force:
        if os.environ.get("TORRENT_SKIP_WARNING"):
            return True
        if load_setting(DISMISSED_KEY, False):
            return True

    with console.status("[accent]Fetching network info…[/accent]", spinner="dots", spinner_style=theme.ACCENT):
        info = _fetch_network_info()

    # (label, value) rows; rows marked optional give way first in a short window.
    rows: list[tuple[str, str, bool]] = []
    verdict: Text | None = None
    if info:
        ip = info.get("query", "unknown")
        isp = info.get("isp", "") or info.get("org", "") or "unknown"
        org = info.get("org", "")
        asname = info.get("asname", "") or info.get("as", "")
        country = info.get("country", "")
        city = info.get("city", "")
        loc = ", ".join(x for x in (city, country) if x)
        is_proxy = bool(info.get("proxy"))
        is_hosting = bool(info.get("hosting"))
        is_mobile = bool(info.get("mobile"))

        rows.append(("Public IP", ip, False))
        rows.append(("ISP", isp, False))
        if org and org != isp:
            rows.append(("Org", org, True))
        if asname:
            rows.append(("ASN", asname, True))
        if loc:
            rows.append(("Location", loc, True))

        # Trust API flags first, fall back to keyword heuristic.
        if is_proxy:
            verdict = Text("✓ Proxy/VPN flagged by network database.", style=f"bold {theme.GOOD}")
        elif is_hosting:
            verdict = Text("✓ Hosting/datacenter IP — likely a VPN exit (not a residential ISP).",
                           style=f"bold {theme.GOOD}")
        elif _looks_like_vpn(f"{isp} {org} {asname}"):
            verdict = Text("✓ VPN provider name detected in network org.", style=f"bold {theme.GOOD}")
        elif is_mobile:
            verdict = Text("! Mobile carrier IP — no VPN. Carrier and peers see this IP.",
                           style=f"bold {theme.BAD}")
        else:
            verdict = Text("! Residential ISP IP — no VPN detected. Your real IP is visible.",
                           style=f"bold {theme.BAD}")
    else:
        verdict = Text("Could not fetch public IP info (offline?).", style=theme.MUTED)

    warning = Text(
        "Any download or stream joins a public BitTorrent swarm. "
        "Every peer and tracker in that swarm sees this IP address. "
        "Seed counts and names are not safety signals — content is not verified."
    )
    keys = "Enter continue  •  " + ("D don't show again  •  " if not force else "") + "Esc abort"

    def frame():
        width, height = console.size.width, console.size.height
        top = theme.header_lines("Network exposure warning", "", width)
        keys_lines = theme.wrap_keys(theme.parse_footer(keys).keys, width)
        middle_parts = [
            theme.wrap_block(verdict, width, console),
            theme.wrap_block(warning, width, console),
        ]
        label_width = max((len(label) for label, _, _ in rows), default=0) + 2
        detail = [(Text(theme.MARGIN + label.ljust(label_width), style=theme.MUTED).append(value, style="bold"),
                   optional) for label, value, optional in rows]
        spaced = height >= 20

        def assemble(include_optional: bool, spacing: bool, header: list[Text]) -> list[Text]:
            blank = [Text("")] if spacing else []
            lines = list(header) + blank
            lines += [line for line, optional in detail if include_optional or not optional]
            for part in middle_parts:
                lines += blank + part
            return lines + blank + keys_lines

        # The warning text and keys always show. In a short window the optional
        # Org / ASN / Location rows go first, then the spacing, then the
        # header's second line.
        lines = assemble(True, spaced, top)
        if len(lines) > height:
            lines = assemble(False, spaced, top)
        if len(lines) > height:
            lines = assemble(False, False, top)
        if len(lines) > height and len(top) > 1:
            lines = assemble(False, False, [theme.header("Network exposure warning", "", width)])
        return Group(*[line.copy() for line in lines])

    dismissed = False
    sys.stdout.write("\033[?1049h\033[?25l\033[2J\033[H")
    sys.stdout.flush()
    try:
        while True:
            _render(None, frame())
            try:
                key = readchar.readkey()
            except KeyboardInterrupt:
                return False
            if key in (readchar.key.ENTER, readchar.key.CR, readchar.key.LF):
                return True
            if not force and key in ("d", "D"):
                save_setting(DISMISSED_KEY, True)
                dismissed = True
                return True
            if key == readchar.key.ESC:
                return False
            if key in (readchar.key.CTRL_C, "\x03"):
                return False
    finally:
        sys.stdout.write("\033[?25h\033[?1049l")
        sys.stdout.flush()
        if dismissed:
            console.print("[muted]Warning dismissed. Re-open via the provider menu.[/muted]")
