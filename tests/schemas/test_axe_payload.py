import pytest
from pydantic import ValidationError

from a11y_health.schemas.axe_payload import AxePayload
from tests.factories import make_axe_payload, make_violation


class TestAxePayloadMissingFields:
    def test_missing_test_subject(self) -> None:
        raw = make_axe_payload()
        del raw["testSubject"]
        with pytest.raises(ValidationError):
            AxePayload.model_validate(raw)

    def test_missing_findings(self) -> None:
        raw = make_axe_payload()
        del raw["findings"]
        with pytest.raises(ValidationError):
            AxePayload.model_validate(raw)


class TestAxePayloadBoundary:
    def test_empty_file_name_rejected(self) -> None:
        raw = make_axe_payload(url="")
        with pytest.raises(ValidationError):
            AxePayload.model_validate(raw)

    def test_null_impact_on_rule_rejected(self) -> None:
        violation = make_violation("color-contrast", "serious")
        violation["impact"] = None
        raw = make_axe_payload(violations=[violation])
        with pytest.raises(ValidationError):
            AxePayload.model_validate(raw)

    def test_invalid_impact_value_rejected(self) -> None:
        violation = make_violation("color-contrast", "severe")
        raw = make_axe_payload(violations=[violation])
        with pytest.raises(ValidationError):
            AxePayload.model_validate(raw)

    def test_wrong_type_violations_rejected(self) -> None:
        raw = make_axe_payload()
        raw["findings"]["violations"] = "not-a-list"
        with pytest.raises(ValidationError):
            AxePayload.model_validate(raw)

    def test_wrong_type_incomplete_rejected(self) -> None:
        raw = make_axe_payload()
        raw["findings"]["incomplete"] = 42
        with pytest.raises(ValidationError):
            AxePayload.model_validate(raw)

    def test_rule_missing_required_fields_rejected(self) -> None:
        raw = make_axe_payload(violations=[{"id": "some-rule"}])
        with pytest.raises(ValidationError):
            AxePayload.model_validate(raw)

    def test_rule_missing_id_rejected(self) -> None:
        raw = make_axe_payload(violations=[{"impact": "serious", "description": "d", "help": "h", "helpUrl": "u"}])
        with pytest.raises(ValidationError):
            AxePayload.model_validate(raw)

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
        with pytest.raises(ValidationError):
            AxePayload.model_validate(raw)


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
        assert {"standard": "wcag", "version": "2.0", "level": "AA"} in rule.classifications
        assert {"standard": "best-practice"} in rule.classifications


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
