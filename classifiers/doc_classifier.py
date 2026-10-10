"""
Document content classifier — determines the best prompt template for a document.

Classifies extracted text into TECHNICAL, FINANCE, or GENERAL based on
regex feature matching. Pure rule-driven, no AI call, zero latency.

Used by the "auto" prompt selection mode to pick the right prompt template
without requiring user intervention.
"""
import re
import logging

logger = logging.getLogger(__name__)


class DocType:
    TECHNICAL = "technical"
    FINANCE = "finance"
    GENERAL = "general"


# Each signal is (compiled_regex, weight).  We scan only the first
# MAX_SCAN_CHARS characters to keep classification fast.
MAX_SCAN_CHARS = 5000

_TECH_SIGNALS = [
    # Code blocks / inline code
    (re.compile(r'```\w+'), 3),
    (re.compile(r'`[A-Za-z_][A-Za-z0-9_.]+`'), 1),
    # API / SDK / protocol keywords
    (re.compile(r'\b(?:API|SDK|REST|GraphQL|gRPC|WebSocket|MQTT)\b'), 2),
    # Infrastructure / DevOps
    (re.compile(r'\b(?:docker|kubernetes|k8s|nginx|apache|terraform|ansible|ci/cd|pipeline)\b', re.I), 2),
    # API URL patterns
    (re.compile(r'https?://\S+/(?:api|v\d)/'), 2),
    # Programming language constructs
    (re.compile(r'\b(?:def |class |function |import |from |require\(|include )'), 2),
    # File extensions in text
    (re.compile(r'\b\w+\.(?:py|js|ts|java|go|rs|cpp|yaml|yml|json|xml|sql|sh|dockerfile)\b', re.I), 1),
    # Diagram / architecture keywords
    (re.compile(r'\b(?:flowchart|sequence|diagram|architecture|topology|schema|pipeline|workflow)\b', re.I), 2),
    # Flow arrows (common in diagram text fragments)
    (re.compile(r'(?:→|->|=>|──|<->|<-->)'), 1),
    # Version numbers
    (re.compile(r'\bv\d+\.\d+(?:\.\d+)?\b'), 1),
    # Technical path patterns
    (re.compile(r'/(?:usr|etc|var|opt|home|api|src|lib|bin)/'), 1),
    # Environment variables
    (re.compile(r'\b[A-Z][A-Z0-9_]{2,}(?:_[A-Z0-9]+)+\b'), 1),
    # HTTP methods
    (re.compile(r'\b(?:GET|POST|PUT|DELETE|PATCH)\s+/'), 2),
    # Port numbers
    (re.compile(r':\d{4,5}\b'), 1),
]

_FIN_SIGNALS = [
    # Chinese financial terms
    (re.compile(r'(?:對帳單|信用卡|帳戶|餘額|匯率|利息|本金|到期|繳費)'), 3),
    (re.compile(r'(?:利率|年化|殖利率|配息|股利|淨值|基金|投資)'), 2),
    (re.compile(r'(?:發票|統一編號|營業稅|稅額|含稅|未稅)'), 2),
    # English financial terms
    (re.compile(r'\b(?:statement|invoice|balance|transaction|ledger|debit|credit)\b', re.I), 2),
    (re.compile(r'\b(?:interest rate|dividend|portfolio|fiscal|revenue|expense)\b', re.I), 2),
    # Currency patterns
    (re.compile(r'(?:NT\$|USD|TWD|JPY|EUR|CNY|HKD|GBP)\s*[\d,]+'), 3),
    (re.compile(r'\$\s*[\d,]+\.\d{2}\b'), 2),
    # Date + amount patterns (typical in transaction rows)
    (re.compile(r'\d{4}[-/]\d{2}[-/]\d{2}.*[\d,]+\.\d{2}'), 2),
    # Account number patterns (partially masked)
    (re.compile(r'\b\d{4}[\s-]?[*Xx]{4,}[\s-]?\d{4}\b'), 3),
]

# Minimum score to classify as non-GENERAL, and the required dominance ratio.
_MIN_SCORE = 8
_DOMINANCE_RATIO = 2.0


def classify(text: str) -> str:
    """
    Classify document content into TECHNICAL, FINANCE, or GENERAL.

    Scans the first MAX_SCAN_CHARS characters for feature signals.
    Returns DocType.TECHNICAL, DocType.FINANCE, or DocType.GENERAL.

    A type is chosen only when its score reaches _MIN_SCORE AND exceeds
    the other type's score by _DOMINANCE_RATIO.  When in doubt, GENERAL
    is returned (safe fallback to default.txt).
    """
    if not text:
        return DocType.GENERAL

    sample = text[:MAX_SCAN_CHARS]
    score_tech = 0
    score_fin = 0

    for pattern, weight in _TECH_SIGNALS:
        hits = len(pattern.findall(sample))
        score_tech += weight * min(hits, 5)  # cap per-signal to avoid a single noisy match dominating

    for pattern, weight in _FIN_SIGNALS:
        hits = len(pattern.findall(sample))
        score_fin += weight * min(hits, 5)

    logger.debug(
        f"[DocClassifier] tech={score_tech}  fin={score_fin}  "
        f"(sample={len(sample)} chars)"
    )

    if score_tech >= _MIN_SCORE and score_tech > score_fin * _DOMINANCE_RATIO:
        return DocType.TECHNICAL
    if score_fin >= _MIN_SCORE and score_fin > score_tech * _DOMINANCE_RATIO:
        return DocType.FINANCE
    return DocType.GENERAL
