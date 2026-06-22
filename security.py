"""Network exposure warning shown at startup."""

import os

import readchar
import requests
from rich.panel import Panel
from rich.text import Text

from constants import console
from state import load_setting, save_setting

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

    with console.status("[bold cyan]Fetching network info...[/bold cyan]", spinner="dots"):
        info = _fetch_network_info()

    body = Text()
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

        body.append("Public IP:  ", style="dim")
        body.append(f"{ip}\n", style="bold white")
        body.append("ISP:        ", style="dim")
        body.append(f"{isp}\n", style="bold white")
        if org and org != isp:
            body.append("Org:        ", style="dim")
            body.append(f"{org}\n", style="bold white")
        if asname:
            body.append("ASN:        ", style="dim")
            body.append(f"{asname}\n", style="bold white")
        if loc:
            body.append("Location:   ", style="dim")
            body.append(f"{loc}\n", style="bold white")
        body.append("\n")

        # Trust API flags first, fall back to keyword heuristic.
        if is_proxy:
            body.append("✓ Proxy/VPN flagged by network database.\n", style="bold green")
        elif is_hosting:
            body.append(
                "✓ Hosting/datacenter IP — likely a VPN exit (not a residential ISP).\n",
                style="bold green",
            )
        elif _looks_like_vpn(f"{isp} {org} {asname}"):
            body.append("✓ VPN provider name detected in network org.\n", style="bold green")
        elif is_mobile:
            body.append(
                "⚠  Mobile carrier IP — no VPN. Carrier and peers see this IP.\n",
                style="bold red",
            )
        else:
            body.append(
                "⚠  Residential ISP IP — no VPN detected. Your real IP is visible.\n",
                style="bold red",
            )
    else:
        body.append("Could not fetch public IP info (offline?).\n", style="dim")

    body.append("\n")
    body.append(
        "Any download or stream joins a public BitTorrent swarm.\n"
        "Every peer and tracker in that swarm sees this IP address.\n"
        "Seed counts and names are not safety signals — content is not verified.\n",
        style="white",
    )
    body.append("\n")
    body.append(" Enter ", style="bold yellow on grey23")
    body.append(" continue     ", style="dim")
    if not force:
        body.append(" D ", style="bold yellow on grey23")
        body.append(" don't show again     ", style="dim")
    body.append(" Esc ", style="bold yellow on grey23")
    body.append(" abort", style="dim")

    panel = Panel(
        body,
        title="[bold red]⚠  Network Exposure Warning[/bold red]",
        border_style="red",
        padding=(1, 2),
    )
    console.print(panel)

    while True:
        key = readchar.readkey()
        if key in (readchar.key.ENTER, readchar.key.CR, readchar.key.LF):
            return True
        if not force and key in ("d", "D"):
            save_setting(DISMISSED_KEY, True)
            console.print("[dim]Warning dismissed. Re-open via the provider menu.[/dim]")
            return True
        if key == readchar.key.ESC:
            return False
        if key in (readchar.key.CTRL_C, "\x03"):
            return False
