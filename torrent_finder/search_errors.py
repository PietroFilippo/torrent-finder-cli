"""Actionable search failures that must not be shown as an empty result set."""


class SearchError(Exception):
    pass


def login_required(provider: str) -> SearchError:
    from torrent_finder.credentials import storage_problem
    problem = storage_problem()
    return SearchError(
        problem or f"{provider}: not logged in. Add your username and password in Credentials on the provider screen."
    )
