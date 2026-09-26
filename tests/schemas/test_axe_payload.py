from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from a11y_health.core.exceptions import InvalidAxePayloadError
from a11y_health.models.classification import Classification
from a11y_health.schemas.axe_payload import AxePayload, parse_axe_payload
from tests.factories import make_axe_payload, make_violation


def _only_error_loc(raw: dict[str, object]) -> tuple[int | str, ...]:
    # A rejection that names one location fails for one reason: a second fault
    # in the document would let the field under test loosen without a red.
    with pytest.raises(ValidationError) as exc_info:
        AxePayload.model_validate(raw)
    [err] = exc_info.value.errors()
    return err["loc"]


class TestAxePayloadMissingFields:
    def test_missing_test_subject(self) -> None:
        raw = make_axe_payload()
        del raw["testSubject"]
        assert _only_error_loc(raw) == ("testSubject",)

    def test_missing_findings(self) -> None:
        raw = make_axe_payload()
        del raw["findings"]
        assert _only_error_loc(raw) == ("findings",)


class TestAxePayloadBoundary:
    def test_empty_file_name_rejected(self) -> None:
        raw = make_axe_payload(url="")
        assert _only_error_loc(raw) == ("testSubject", "fileName")

    def test_null_impact_on_rule_rejected(self) -> None:
        violation = make_violation("color-contrast", "serious")
        violation["impact"] = None
        raw = make_axe_payload(violations=[violation])
        assert _only_error_loc(raw) == ("findings", "violations", 0, "impact")

    def test_invalid_impact_value_rejected(self) -> None:
        # The node keeps a valid impact, so loosening the rule's own impact
        # type reds this rather than the node's rejection covering for it.
        violation = make_violation("color-contrast", "serious")
        violation["impact"] = "severe"
        raw = make_axe_payload(violations=[violation])
        assert _only_error_loc(raw) == ("findings", "violations", 0, "impact")

    def test_wrong_type_violations_rejected(self) -> None:
        raw = make_axe_payload()
        raw["findings"]["violations"] = "not-a-list"
        assert _only_error_loc(raw) == ("findings", "violations")

    def test_wrong_type_incomplete_rejected(self) -> None:
        raw = make_axe_payload()
        raw["findings"]["incomplete"] = 42
        assert _only_error_loc(raw) == ("findings", "incomplete")

    # Both required-field cases start from a rule with valid tags and nodes, so
    # the category derivation passes and the missing field is what fires. Each
    # reds when its field is made optional.

    def test_rule_missing_required_fields_rejected(self) -> None:
        violation = make_violation("color-contrast", "serious")
        for field in ("impact", "description", "help", "helpUrl"):
            del violation[field]
        raw = make_axe_payload(violations=[violation])
        with pytest.raises(ValidationError) as exc_info:
            AxePayload.model_validate(raw)
        reported = {(err["loc"], err["msg"]) for err in exc_info.value.errors()}
        assert reported == {
            (("findings", "violations", 0, "impact"), "Field required"),
            (("findings", "violations", 0, "description"), "Field required"),
            (("findings", "violations", 0, "help"), "Field required"),
            (("findings", "violations", 0, "helpUrl"), "Field required"),
        }

    def test_rule_missing_id_rejected(self) -> None:
        violation = make_violation("color-contrast", "serious")
        del violation["id"]
        raw = make_axe_payload(violations=[violation])
        with pytest.raises(ValidationError) as exc_info:
            AxePayload.model_validate(raw)
        [err] = exc_info.value.errors()
        assert err["loc"] == ("findings", "violations", 0, "id")
        assert err["msg"] == "Field required"

    def test_non_dict_rule_entry_rejected(self) -> None:
        raw = make_axe_payload(violations=[42])
        assert _only_error_loc(raw) == ("findings", "violations", 0)

    def test_empty_violations_and_incomplete_accepted(self) -> None:
        raw = make_axe_payload(violations=[], incomplete=[])
        payload = AxePayload.model_validate(raw)
        assert payload.findings.violations == []
        assert payload.findings.incomplete == []


class TestAxeNodeFields:
    def test_node_without_failure_summary_accepted(self) -> None:
        violation = make_violation("color-contrast", "serious")
        assert "failureSummary" not in violation["nodes"][0]
        raw = make_axe_payload(violations=[violation])
        payload = AxePayload.model_validate(raw)
        assert payload.findings.violations[0].nodes[0].failure_summary is None

    def test_node_with_failure_summary_parsed(self) -> None:
        violation = make_violation("color-contrast", "serious")
        violation["nodes"][0]["failureSummary"] = "Fix this"
        raw = make_axe_payload(violations=[violation])
        payload = AxePayload.model_validate(raw)
        assert payload.findings.violations[0].nodes[0].failure_summary == "Fix this"


class TestAxeNodeChecks:
    def test_checks_parsed_from_payload(self) -> None:
        violation = make_violation("color-contrast", "serious")
        violation["nodes"][0]["any"] = [{"id": "check-1", "data": None}]
        violation["nodes"][0]["all"] = [{"id": "check-2", "data": None}]
        violation["nodes"][0]["none"] = [{"id": "check-3", "data": None}]
        raw = make_axe_payload(violations=[violation])
        payload = AxePayload.model_validate(raw)
        node = payload.findings.violations[0].nodes[0]
        assert node.any == [{"id": "check-1", "data": None}]
        assert node.all == [{"id": "check-2", "data": None}]
        assert node.none == [{"id": "check-3", "data": None}]

    def test_checks_default_to_empty_lists(self) -> None:
        violation = make_violation("color-contrast", "serious")
        del violation["nodes"][0]["any"]
        del violation["nodes"][0]["all"]
        del violation["nodes"][0]["none"]
        raw = make_axe_payload(violations=[violation])
        payload = AxePayload.model_validate(raw)
        node = payload.findings.violations[0].nodes[0]
        assert node.any == []
        assert node.all == []
        assert node.none == []

    def test_checks_reject_non_list(self) -> None:
        violation = make_violation("color-contrast", "serious")
        violation["nodes"][0]["any"] = "not-a-list"
        raw = make_axe_payload(violations=[violation])
        assert _only_error_loc(raw) == ("findings", "violations", 0, "nodes", 0, "any")


class TestAxeFindingsPassesInapplicable:
    def test_passes_and_inapplicable_parsed(self) -> None:
        raw = make_axe_payload()
        raw["findings"]["passes"] = [{"id": "rule-1"}, {"id": "rule-2"}]
        raw["findings"]["inapplicable"] = [{"id": "rule-3"}]
        payload = AxePayload.model_validate(raw)
        assert len(payload.findings.passes) == 2
        assert len(payload.findings.inapplicable) == 1

    def test_passes_and_inapplicable_default_to_empty(self) -> None:
        raw = make_axe_payload()
        del raw["findings"]["passes"]
        del raw["findings"]["inapplicable"]
        payload = AxePayload.model_validate(raw)
        assert payload.findings.passes == []
        assert payload.findings.inapplicable == []


class TestAxeRuleSemanticValidation:
    def test_reject_rule_missing_category_tag(self) -> None:
        violation = make_violation("color-contrast", "serious")
        violation["tags"] = ["wcag2a", "best-practice"]
        raw = make_axe_payload(violations=[violation])
        with pytest.raises(ValidationError) as exc_info:
            AxePayload.model_validate(raw)
        err = exc_info.value.errors()[0]
        assert "findings" in err["loc"]
        assert "violations" in err["loc"]
        assert "No category tag found" in err["msg"]

    def test_reject_rule_unknown_category_tag(self) -> None:
        violation = make_violation("color-contrast", "serious")
        violation["tags"] = ["cat.bogus"]
        raw = make_axe_payload(violations=[violation])
        with pytest.raises(ValidationError) as exc_info:
            AxePayload.model_validate(raw)
        err = exc_info.value.errors()[0]
        assert "findings" in err["loc"]
        assert "violations" in err["loc"]
        assert "Unknown category: bogus" in err["msg"]

    def test_classified_fields_attached_to_rule(self) -> None:
        violation = make_violation("color-contrast", "serious")
        violation["tags"] = ["cat.color", "wcag2aa", "wcag143", "best-practice"]
        raw = make_axe_payload(violations=[violation])
        payload = AxePayload.model_validate(raw)
        rule = payload.findings.violations[0]
        assert rule.category.value == "color"
        assert rule.wcag_criteria == ["1.4.3"]
        assert Classification(standard="wcag", version="2.0", level="AA") in rule.classifications
        assert Classification(standard="best-practice") in rule.classifications


class TestAxePayloadValid:
    def test_valid_payload_parses(self) -> None:
        raw = make_axe_payload(
            url="https://example.com/home",
            violations=[make_violation("color-contrast", "serious")],
            incomplete=[make_violation("aria-label", "moderate")],
        )
        payload = AxePayload.model_validate(raw)

        assert payload.test_subject.file_name == "https://example.com/home"
        assert len(payload.findings.violations) == 1
        assert payload.findings.violations[0].id == "color-contrast"
        assert len(payload.findings.incomplete) == 1


class TestAxePayloadIdentityFields:
    # `name` and `endTime` are optional at the boundary: absent is fine, present
    # is validated. Both readers (the CLI at load, the server at upload) get the
    # same verdict from the same crossing.

    def test_name_present_is_carried(self) -> None:
        payload = parse_axe_payload(make_axe_payload(name="Humana Home"))
        assert payload.name == "Humana Home"

    def test_name_absent_is_none(self) -> None:
        raw = make_axe_payload()
        del raw["name"]
        assert parse_axe_payload(raw).name is None

    def test_name_non_string_is_invalid(self) -> None:
        raw = make_axe_payload()
        raw["name"] = 42
        with pytest.raises(InvalidAxePayloadError, match="name"):
            parse_axe_payload(raw)

    def test_end_time_absent_is_none(self) -> None:
        raw = make_axe_payload()
        assert "endTime" not in raw
        assert parse_axe_payload(raw).end_time is None

    def test_end_time_null_is_none(self) -> None:
        # Present-but-null is a different branch from absent: pydantic runs
        # the before-validator only when the key is there.
        raw = make_axe_payload()
        raw["endTime"] = None
        assert parse_axe_payload(raw).end_time is None

    def test_end_time_empty_string_is_absent(self) -> None:
        # What parsed before the move still parses: the old loader read every
        # falsy value as absent, and an export with `"endTime": ""` fell back
        # to the directory mtime.
        assert parse_axe_payload(make_axe_payload(end_time="")).end_time is None

    @pytest.mark.parametrize("end_time", [1_700_000_000, "last Tuesday", 0, False])
    def test_end_time_present_but_unreadable_is_invalid(self, end_time: object) -> None:
        # Strict when present. The message names the field and the accepted
        # shape, never the value — it reaches the wire verbatim.
        with pytest.raises(InvalidAxePayloadError, match="endTime: must be an ISO 8601 timestamp$"):
            parse_axe_payload(make_axe_payload(end_time=end_time))

    def test_snake_case_end_time_is_an_unmodeled_key(self) -> None:
        # Only the axe spelling is read; a snake_case key can neither supply
        # the observation time nor fail the load.
        raw = make_axe_payload(unmodeled={"end_time": "garbage"})
        assert parse_axe_payload(raw).end_time is None

    def test_missing_test_subject_is_reported_before_a_mistyped_identity_field(self) -> None:
        # Only the first error reaches the operator, and declaration order picks
        # it: a document that is not axe JSON hears about `testSubject` first.
        # Reds when `name` or `end_time` is declared above `test_subject`.
        raw = make_axe_payload(end_time="last Tuesday")
        raw["name"] = 42
        del raw["testSubject"]
        with pytest.raises(InvalidAxePayloadError) as exc_info:
            parse_axe_payload(raw)
        assert exc_info.value.reason == "testSubject: Field required"

    def test_non_object_document_is_named_as_such(self) -> None:
        # No field to point at, so the message names the document rather than
        # leaking the model class pydantic would mention.
        with pytest.raises(InvalidAxePayloadError, match="document is not a JSON object"):
            parse_axe_payload([make_axe_payload()])


class TestAxePayloadEndTimeCompatibility:
    # The forms in use today, pinned so relocating the parser into the schema
    # shifts nothing: an offset-less value is assumed UTC (the CLI's posture
    # before the move), a numeric offset is kept, and `Z` is UTC. Reds when
    # the validator returns a naive datetime for the offset-less form.

    @pytest.mark.parametrize(
        ("end_time", "expected"),
        [
            ("2026-05-01T12:00:00", datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC)),
            ("2026-03-30T11:55:52-0400", datetime(2026, 3, 30, 11, 55, 52, tzinfo=timezone(timedelta(hours=-4)))),
            ("2026-04-01T12:00:00Z", datetime(2026, 4, 1, 12, 0, 0, tzinfo=UTC)),
            ("2026-04-01T12:00:00.123456+00:00", datetime(2026, 4, 1, 12, 0, 0, 123456, tzinfo=UTC)),
        ],
    )
    def test_accepted_form_parses_to_the_same_instant(self, end_time: str, expected: datetime) -> None:
        parsed = parse_axe_payload(make_axe_payload(end_time=end_time)).end_time
        assert parsed == expected
        assert parsed is not None and parsed.utcoffset() == expected.utcoffset()
