"""Provider registry - import and expose all available providers."""

from providers.movie_provider import MovieProvider

# Registry of all available providers (order = display order)
PROVIDERS: list = [
    MovieProvider(),
]


def get_provider(name: str):
    """Look up a provider by name (case-insensitive)."""
    for p in PROVIDERS:
        if p.name.lower() == name.lower():
            return p
    return None
