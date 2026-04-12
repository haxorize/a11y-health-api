import enum


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


class Category(enum.Enum):
    ARIA = "aria"
    COLOR = "color"
    FORMS = "forms"
    KEYBOARD = "keyboard"
    LANGUAGE = "language"
    NAME_ROLE_VALUE = "name-role-value"
    PARSING = "parsing"
    SEMANTICS = "semantics"
    SENSORY_AND_VISUAL_CUES = "sensory-and-visual-cues"
    STRUCTURE = "structure"
    TABLES = "tables"
    TEXT_ALTERNATIVES = "text-alternatives"
    TIME_AND_MEDIA = "time-and-media"


class ScanRunStatus(enum.Enum):
    PENDING = "pending"
    COMPLETED = "completed"
