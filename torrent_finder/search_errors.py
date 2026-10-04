"""Actionable search failures that must not be shown as an empty result set."""


class SearchError(Exception):
    """A failure to show instead of "no results".

    *status* names the diagnostic status (e.g. "blocked", "rejected_login")
    when the message alone would be ambiguous.
    """

    def __init__(self, message: str = "", status: str | None = None) -> None:
        super().__init__(message)
        self.status = status


def login_required(provider: str) -> SearchError:
    from torrent_finder.credentials import storage_problem
    problem = storage_problem()
    return SearchError(
        problem or f"{provider}: not logged in. Add your username and password in Credentials on the provider screen."
    )
