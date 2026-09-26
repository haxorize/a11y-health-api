"""The wire shape of a coded error body, in both readings.

Split out from `error_contract.py` so that reading one does not require the web
framework: `error_contract` imports FastAPI and Starlette to register handlers
and generate declarations, and the CLI — which only ever *reads* an error body —
would otherwise load all of it to parse two fields.

The two readings live together because they are twins, and twins drift when
separated: `ErrorBody` is what this deployment serves, `ClientErrorBody` is what
a client off it accepts. `error_contract.py` owns everything else — the mode
table, the handler, the per-operation declarations.
"""

import enum

from pydantic import BaseModel, ValidationError


class ErrorCode(enum.StrEnum):
    NOT_FOUND = "not_found"
    DUPLICATE_ROOT = "duplicate_root"
    DUPLICATE_SLUG = "duplicate_slug"
    HAS_DEPENDENTS = "has_dependents"
    INVALID_STATUS_TRANSITION = "invalid_status_transition"
    SCAN_RUN_COMPLETED = "scan_run_completed"
    EMPTY_SCAN_RUN = "empty_scan_run"
    CIRCULAR_REFERENCE = "circular_reference"
    CONCURRENT_ROLLUP = "concurrent_rollup"
    INVALID_CURSOR = "invalid_cursor"
    INVALID_AXE_PAYLOAD = "invalid_axe_payload"


class ErrorBody(BaseModel):
    code: ErrorCode
    message: str


class ClientErrorBody(BaseModel):
    """The same body, as a client off this deployment reads it: the contract's
    two fields, with `code` left an open string.

    `ErrorBody` narrows `code` to the `ErrorCode` vocabulary *this* build knows,
    which is right for serving and wrong for reading. A client validating an
    answer against its own vocabulary would reject exactly the codes it most
    needs to show the operator — the ones a server deployed ahead of it added.
    """

    code: str
    message: str


def read_error_body(body: bytes | str) -> ClientErrorBody | None:
    """The coded body carried by an error response, or `None` when the response
    doesn't carry one — a framework 422, an HTML page from a proxy, an empty
    body. `None` is the caller's cue to fall back to the raw text.
    """
    try:
        return ClientErrorBody.model_validate_json(body)
    except ValidationError:
        return None
