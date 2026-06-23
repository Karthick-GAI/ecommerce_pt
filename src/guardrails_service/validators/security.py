"""
Security input validators.

Detects injection attacks and other malicious input patterns before they
reach the database or downstream services. All patterns use re.search so
partial matches within larger strings are caught.

Severity mapping → risk weight:
  critical = 40  (auto-block on one hit)
  high     = 20
  medium   = 10
  low      =  5
"""
import re
from dataclasses import dataclass, field


@dataclass
class Violation:
    rule:     str
    severity: str
    message:  str
    matched:  str = ""


# ── SQL Injection ─────────────────────────────────────────────────────────────

_SQL_PATTERNS: list[tuple[str, str, str]] = [
    # (compiled_pattern_source, severity, message)

    # DDL / DML via stacked query
    (r"(?i);\s*(drop|delete|truncate|alter|create|insert|update)\s+\w",
     "critical", "SQL DDL/DML stacked-query injection"),

    # Classic UNION-based
    (r"(?i)\bunion\b.{0,30}\bselect\b",
     "critical", "SQL UNION SELECT injection"),

    # Boolean tautologies  '1'='1' or 1=1
    (r"""(?i)(['"])\s*(?:or|and)\s*\1?\s*\d+\s*=\s*\d+""",
     "high", "SQL boolean tautology injection"),
    (r"""(?i)\bor\s+['"]?\d+['"]?\s*=\s*['"]?\d+['"]?""",
     "high", "SQL OR-based boolean injection"),

    # Comment terminators
    (r"(?i)(--|#|/\*).{0,80}",
     "high", "SQL comment injection"),

    # EXEC / EXECUTE
    (r"(?i)\b(exec|execute)\s*\(",
     "critical", "SQL EXEC injection"),

    # Dangerous stored procs (MSSQL / MySQL)
    (r"(?i)(xp_cmdshell|sp_executesql|sp_oacreate|openrowset|opendatasource)",
     "critical", "SQL dangerous stored procedure"),

    # Benchmark / SLEEP (blind timing attacks)
    (r"(?i)\b(sleep|benchmark|pg_sleep|waitfor\s+delay)\s*\(",
     "high", "SQL time-based blind injection"),

    # INFORMATION_SCHEMA probing
    (r"(?i)(information_schema|sys\.tables|sysobjects|pg_catalog)",
     "high", "SQL schema enumeration attempt"),

    # Hex / char encoding evasion
    (r"(?i)(0x[0-9a-f]{4,}|char\s*\(\s*\d{1,3}\s*\))",
     "medium", "SQL hex/char encoding evasion"),
]

_COMPILED_SQL = [(re.compile(p), sev, msg) for p, sev, msg in _SQL_PATTERNS]


def check_sql_injection(text: str) -> list[Violation]:
    violations = []
    for pattern, severity, message in _COMPILED_SQL:
        m = pattern.search(text)
        if m:
            matched = text[max(0, m.start()-5):m.end()+5].replace("\n", " ")
            violations.append(Violation("sql_injection", severity, message, matched))
    return violations


# ── XSS ──────────────────────────────────────────────────────────────────────

_XSS_PATTERNS: list[tuple[str, str, str]] = [
    (r"(?i)<\s*script[^>]*>",
     "critical", "XSS: <script> tag injection"),

    (r"(?i)javascript\s*:",
     "high", "XSS: javascript: URI injection"),

    (r"(?i)on(?:load|error|click|mouse(?:over|out|move)|submit|focus|blur|"
     r"change|input|keydown|keyup|keypress|drag|drop|copy|paste|wheel)\s*=",
     "high", "XSS: inline event handler injection"),

    (r"(?i)<\s*(?:iframe|frame|embed|object|applet|base|meta|link)[^>]*>",
     "high", "XSS: dangerous HTML tag injection"),

    (r"(?i)(?:document\s*\.\s*(?:cookie|write|location)|window\s*\.\s*location)",
     "high", "XSS: DOM manipulation attempt"),

    (r"(?i)(?:eval|setTimeout|setInterval|Function)\s*\(",
     "medium", "XSS: dangerous JS function call"),

    (r"(?i)(?:&#x[0-9a-f]+;|&#\d+;)",
     "medium", "XSS: HTML entity encoding evasion"),

    # Data URIs with active content
    (r"(?i)data\s*:\s*(?:text/html|application/javascript)",
     "high", "XSS: data URI with active content"),

    # SVG-based XSS
    (r"(?i)<\s*svg[^>]*>",
     "medium", "XSS: SVG tag injection"),

    # Template injection markers
    (r"(?:\{\{|\}\}|\{%|%\}|\$\{)",
     "low", "Potential template injection syntax"),
]

_COMPILED_XSS = [(re.compile(p), sev, msg) for p, sev, msg in _XSS_PATTERNS]


def check_xss(text: str) -> list[Violation]:
    violations = []
    for pattern, severity, message in _COMPILED_XSS:
        m = pattern.search(text)
        if m:
            matched = text[max(0, m.start()-5):m.end()+5].replace("\n", " ")
            violations.append(Violation("xss", severity, message, matched))
    return violations


# ── Path Traversal ────────────────────────────────────────────────────────────

_PATH_PATTERNS: list[tuple[str, str, str]] = [
    (r"\.\./|\.\.\\",
     "high", "Path traversal: ../ detected"),

    (r"(?i)(%2e%2e%2f|%2e%2e/|\.\.%2f|%2e%2e%5c)",
     "high", "Path traversal: URL-encoded traversal"),

    (r"(?i)(?:etc/passwd|etc/shadow|etc/hosts|proc/self|win\.ini|boot\.ini|"
     r"web\.config|\.env|\.git/|id_rsa)",
     "critical", "Path traversal: sensitive file target"),
]

_COMPILED_PATH = [(re.compile(p), sev, msg) for p, sev, msg in _PATH_PATTERNS]


def check_path_traversal(text: str) -> list[Violation]:
    violations = []
    for pattern, severity, message in _COMPILED_PATH:
        m = pattern.search(text)
        if m:
            violations.append(Violation("path_traversal", severity, message, m.group()))
    return violations


# ── Command Injection ─────────────────────────────────────────────────────────

_CMD_PATTERNS: list[tuple[str, str, str]] = [
    (r"`[^`]+`",
     "critical", "Command injection: backtick execution"),

    (r"\$\([^)]+\)",
     "critical", "Command injection: $() subshell"),

    (r"(?:;|\|\||&&)\s*(?:ls|cat|rm|chmod|wget|curl|nc|bash|sh|python|perl|ruby|php)\b",
     "critical", "Command injection: shell command chaining"),

    (r"(?i)(?:/bin/|/usr/bin/|/sbin/)(?:sh|bash|python|perl|nc|wget|curl)",
     "critical", "Command injection: absolute path execution"),

    (r"(?i)\b(?:whoami|ifconfig|ipconfig|ping|tracert|netstat|nslookup|dig)\b",
     "medium", "Command injection: system recon command"),
]

_COMPILED_CMD = [(re.compile(p), sev, msg) for p, sev, msg in _CMD_PATTERNS]


def check_command_injection(text: str) -> list[Violation]:
    violations = []
    for pattern, severity, message in _COMPILED_CMD:
        m = pattern.search(text)
        if m:
            violations.append(Violation("command_injection", severity, message, m.group()))
    return violations


# ── Null byte / control char injection ────────────────────────────────────────

def check_null_byte(text: str) -> list[Violation]:
    violations = []
    if "\x00" in text or "%00" in text.lower():
        violations.append(Violation("null_byte", "high", "Null byte injection detected", "\\x00"))
    if any(ord(c) < 32 and c not in ("\t", "\n", "\r") for c in text):
        violations.append(Violation("control_chars", "medium", "Non-printable control characters in input"))
    return violations


# ── Combined security scan ────────────────────────────────────────────────────

SEVERITY_WEIGHT = {"critical": 40, "high": 20, "medium": 10, "low": 5}


def scan_input(text: str, context: str = "any") -> list[Violation]:
    """
    Run all applicable security checks for a given context.
    Returns deduplicated violations sorted by severity.
    """
    if not text or not isinstance(text, str):
        return []

    violations: list[Violation] = []

    # SQL injection applies to all contexts (could be hiding anywhere)
    violations.extend(check_sql_injection(text))

    # XSS is relevant in all contexts where content might be rendered
    if context in ("any", "search", "name", "address", "comment"):
        violations.extend(check_xss(text))

    # Path traversal applies to search and arbitrary input
    if context in ("any", "search", "comment"):
        violations.extend(check_path_traversal(text))

    # Command injection in generic contexts
    if context in ("any", "search", "comment"):
        violations.extend(check_command_injection(text))

    violations.extend(check_null_byte(text))

    # Deduplicate by rule — keep the first (highest severity) hit per rule
    seen: set[str] = set()
    unique: list[Violation] = []
    for v in violations:
        key = v.rule + v.message[:30]
        if key not in seen:
            seen.add(key)
            unique.append(v)

    # Sort by severity descending
    order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    unique.sort(key=lambda v: order.get(v.severity, 4))
    return unique


def compute_risk_score(violations: list[Violation]) -> int:
    """Additive risk score, capped at 100."""
    return min(100, sum(SEVERITY_WEIGHT.get(v.severity, 5) for v in violations))
