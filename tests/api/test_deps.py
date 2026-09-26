from typing import get_args

from fastapi.params import Depends

from a11y_health.api.deps import DbSession


def test_the_request_session_commits_before_the_response_is_sent() -> None:
    # The default "request" scope commits after the response, which races the
    # client's next request (docs/solutions/
    # yield-teardown-commit-races-next-request.md). No endpoint test can see
    # the race, so the keyword is read off the declaration.
    (dependency,) = [meta for meta in get_args(DbSession)[1:] if isinstance(meta, Depends)]

    assert dependency.scope == "function"
