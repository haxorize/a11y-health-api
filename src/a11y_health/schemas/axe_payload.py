from pydantic import BaseModel, ConfigDict, Field

from a11y_health.models.enums import Impact


class AxeNode(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    html: str
    target: list[str]
    impact: Impact
    failure_summary: str | None = Field(default=None, alias="failureSummary")


class AxeRule(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    impact: Impact
    description: str
    help: str
    help_url: str = Field(alias="helpUrl")
    tags: list[str]
    nodes: list[AxeNode]


class AxeFindings(BaseModel):
    violations: list[AxeRule]
    incomplete: list[AxeRule]


class AxeTestSubject(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    file_name: str = Field(min_length=1, alias="fileName")


class AxePayload(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    test_subject: AxeTestSubject = Field(alias="testSubject")
    findings: AxeFindings
