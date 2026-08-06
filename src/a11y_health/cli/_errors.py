"""The one type the whole CLI shares.

It sits alone so that no module in the package has to import from another just
to declare a failure: `_scan` and `_client` subclass it, `_terminal` catches it,
and none of them depend on each other to do so. `core/exceptions.py` holds
`DomainError` the same way, for the same reason.
"""


class CliError(Exception):
    """Base for expected, operator-facing CLI failures. `main()` prints these as
    a single `ERROR:` line and exits non-zero instead of dumping a traceback."""
