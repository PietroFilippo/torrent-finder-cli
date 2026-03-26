"""Movie torrent provider — searches video/movie categories."""

from providers.base import BaseProvider


class MovieProvider(BaseProvider):
    name = "Movies"
    icon = "🎬"
    categories = [201, 207]  # Movies, HD Movies
