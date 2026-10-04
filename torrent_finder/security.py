"""Network exposure warning shown at startup."""

import os
import sys

import readchar
import requests
from rich.cells import cell_len
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
        room = theme.inner_width(width)
        # rank 0 = always shown (Public IP), 1 = ISP, 2 = optional (Org / ASN / Location)
        detail = []
        for index, (label, value, optional) in enumerate(rows):
            line = Text(theme.MARGIN + label.ljust(label_width), style=theme.MUTED, no_wrap=True, overflow="ellipsis")
            line.append(value, style="bold")
            line.truncate(room + len(theme.MARGIN), overflow="ellipsis")
            detail.append((line, 2 if optional else min(index, 1)))
        spaced = height >= 20
        one_line_header = [theme.header("Network exposure warning", "", width)]

        def assemble(max_rank: int, spacing: bool, header: list[Text], parts: list[list[Text]]) -> list[Text]:
            blank = [Text("")] if spacing else []
            lines = list(header) + blank
            lines += [line for line, rank in detail if rank <= max_rank]
            for part in parts:
                lines += blank + part
            return lines + blank + keys_lines

        # The verdict, the warning text and the keys always show. In a short
        # window the optional rows go first, then the spacing, the header's
        # second line and the ISP row; only then is the warning text cut short.
        for max_rank, spacing, header in ((2, spaced, top), (1, spaced, top), (1, False, top),
                                          (1, False, one_line_header), (0, False, one_line_header)):
            lines = assemble(max_rank, spacing, header, middle_parts)
            if len(lines) <= height:
                break
        else:
            verdict_lines, warning_lines = middle_parts
            keep = max(1, height - (len(lines) - len(warning_lines)))
            if keep < len(warning_lines):
                warning_lines = warning_lines[:keep]
                last = warning_lines[-1]
                last.truncate(max(1, cell_len(last.plain) - 1))
                last.append("…")
            lines = assemble(0, False, one_line_header, [verdict_lines, warning_lines])
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
