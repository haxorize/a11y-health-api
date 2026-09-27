"""The single source of App Slugs (ADR 0019): every Slug in existence comes
from `derive_slug` — the API creation path, the CLI's App resolution, and the
one-time re-derivation migration all import it, so `slug == derive(name)`
holds by construction.

It also holds NAME_MAX_LENGTH, the name bound of a Brand, an Org Unit and an
App, beside SLUG_MAX_LENGTH, so both length bounds have one home. The models
import them from here, which stays acyclic because this module imports
nothing from the package (ADR 0024's #173 amendment)."""

import re
import unicodedata
from collections.abc import Mapping

# The one spelling of each bound. The length check constraints and the request
# schemas read them here rather than off a model, so derivation never imports
# one. The name bound does not bound the slug: NFKD folding expands
# compatibility characters ("ﬃ" → "ffi"), so derivation enforces it itself.
NAME_MAX_LENGTH = 255
SLUG_MAX_LENGTH = 255


def derive_slug(name: str) -> str:
    """Raises ValueError when the name derives to nothing (symbols-only or
    fully non-Latin) or past SLUG_MAX_LENGTH — no caller wants either slug."""
    folded = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", folded.lower()).strip("-")
    if not slug:
        raise ValueError(f"name {name!r} derives to an empty slug")
    if len(slug) > SLUG_MAX_LENGTH:
        raise ValueError(f"name {name!r} derives to a slug longer than {SLUG_MAX_LENGTH} characters")
    return slug


def rederive_slugs(names_by_id: Mapping[int, str]) -> dict[int, str]:
    """Raises ValueError if any name fails derivation or two rows collide
    post-derivation — the re-derivation migration must fail loudly, never
    silently merge or drop an App."""
    slugs: dict[int, str] = {}
    invalid: list[str] = []
    for row_id, name in names_by_id.items():
        try:
            slugs[row_id] = derive_slug(name)
        except ValueError as exc:
            invalid.append(f"id={row_id}: {exc}")
    if invalid:
        raise ValueError(f"names failing derivation: {'; '.join(invalid)}")

    by_slug: dict[str, list[int]] = {}
    for row_id, slug in slugs.items():
        by_slug.setdefault(slug, []).append(row_id)
    collisions = {slug: ids for slug, ids in by_slug.items() if len(ids) > 1}
    if collisions:
        detail = "; ".join(
            f"{slug!r} from {[f'id={i} name={names_by_id[i]!r}' for i in ids]}" for slug, ids in collisions.items()
        )
        raise ValueError(f"post-derivation slug collisions: {detail}")

    return slugs
