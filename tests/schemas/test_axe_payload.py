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


class TestAxeNodeChecksExcluded:
    def test_checks_fields_ignored_by_schema(self) -> None:
        violation = make_violation("color-contrast", "serious")
        assert "any" in violation["nodes"][0]
        raw = make_axe_payload(violations=[violation])
        payload = AxePayload.model_validate(raw)
        node = payload.findings.violations[0].nodes[0]
        assert not hasattr(node, "checks")
        assert not hasattr(node, "any")
        assert not hasattr(node, "all")
        assert not hasattr(node, "none")


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
