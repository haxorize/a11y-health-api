import pytest

from a11y_health.core.slug import derive_slug, rederive_slugs


def test_derive_slug_folds_case_and_collapses_punctuation() -> None:
    assert derive_slug("My App (Prod)") == "my-app-prod"


def test_derive_slug_folds_accents_to_ascii() -> None:
    assert derive_slug("Café Menü") == "cafe-menu"


def test_derive_slug_trims_leading_and_trailing_separators() -> None:
    assert derive_slug("  --My App--  ") == "my-app"


def test_derive_slug_preserves_digits_and_domain_names() -> None:
    assert derive_slug("go365.humana.com") == "go365-humana-com"


def test_derive_slug_symbols_only_fails_loudly() -> None:
    with pytest.raises(ValueError, match="empty slug"):
        derive_slug("!!! ($%) !!!")


def test_derive_slug_fully_non_latin_fails_loudly() -> None:
    with pytest.raises(ValueError, match="empty slug"):
        derive_slug("日本語")


def test_derive_slug_nfkd_expansion_past_max_length_fails_loudly() -> None:
    # NFKD folds each "ﬃ" to "ffi", so 100 chars in → 300 slug chars out
    with pytest.raises(ValueError, match="longer than 255"):
        derive_slug("ﬃ" * 100)


def test_rederive_slugs_maps_legacy_names_to_derived_form() -> None:
    assert rederive_slugs({1: "My App (Prod)", 2: "foo.com"}) == {1: "my-app-prod", 2: "foo-com"}


def test_rederive_slugs_fails_loudly_on_post_derivation_collision() -> None:
    with pytest.raises(ValueError, match="my-app"):
        rederive_slugs({1: "My App", 2: "my app!"})


def test_rederive_slugs_fails_loudly_on_empty_derivation() -> None:
    with pytest.raises(ValueError, match="empty"):
        rederive_slugs({1: "!!!"})


def test_rederive_slugs_reports_every_failing_row() -> None:
    with pytest.raises(ValueError, match=r"id=1.*id=3"):
        rederive_slugs({1: "!!!", 2: "fine.com", 3: "ﬃ" * 100})
