import enum


class Brand(enum.Enum):
    HUMANA = "Humana"
    CENTERWELL = "CenterWell"
    GO365 = "Go365"
    CAREPLUS = "CarePlus"
    RELIANCE = "Reliance"


class FindingType(enum.Enum):
    VIOLATION = "violation"
    INCOMPLETE = "incomplete"


class Impact(enum.Enum):
    CRITICAL = "critical"
    SERIOUS = "serious"
    MODERATE = "moderate"
    MINOR = "minor"


class PageHealth(enum.Enum):
    CRITICAL = "critical"
    SERIOUS = "serious"
    FAIR = "fair"
    GOOD = "good"


class ScanRunStatus(enum.Enum):
    PENDING = "pending"
    COMPLETED = "completed"
