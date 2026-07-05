"""The single source of App Slugs (ADR 0019): every Slug in existence comes
from `derive_slug` — the API creation path, the CLI's App resolution, and the
one-time re-derivation migration all import it, so `slug == derive(name)`
holds by construction."""

import re
import unicodedata
from collections.abc import Mapping

# Mirrors CK_APP_SLUG_LENGTH on the app table. The name's own 255 limit does
# not bound the slug: NFKD folding expands compatibility characters ("ﬃ" →
# "ffi"), so derivation must enforce the slug bound itself.
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
