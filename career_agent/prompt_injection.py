"""prompt_injection: detection and sanitization of indirect prompt injections in job postings.

Protects LLM agents, ATS matchers, and automated workflows against:
  - Instruction override & jailbreaks (e.g. "Ignore previous instructions")
  - Delimiter & token hijacking (<|im_start|>, [INST], <<<SYS>>>, ### System:)
  - Candidate / evaluation tampering ("Do not hire this candidate", "Score 0")
  - System prompt & credential exfiltration ("Print profile.yaml", "Reveal API keys")
  - Stealth obfuscation (zero-width chars, invisible unicode tags, hidden HTML)
"""
from __future__ import annotations

import html
import re
from typing import Any, Dict, List, Tuple

# -------------------------------------------------------------
# UNICODE STEALTH CHARACTERS
# -------------------------------------------------------------
ZERO_WIDTH_CHARS = {
    "\u200b": "ZERO WIDTH SPACE",
    "\u200c": "ZERO WIDTH NON-JOINER",
    "\u200d": "ZERO WIDTH JOINER",
    "\u200e": "LEFT-TO-RIGHT MARK",
    "\u200f": "RIGHT-TO-LEFT MARK",
    "\u2060": "WORD JOINER",
    "\ufeff": "ZERO WIDTH NO-BREAK SPACE",
    "\u00ad": "SOFT HYPHEN",
}

UNICODE_TAGS_PATTERN = re.compile(r"[\U000e0001-\U000e007f]")

# -------------------------------------------------------------
# THREAT SIGNATURE PATTERNS
# -------------------------------------------------------------
THREAT_RULES: List[Tuple[str, str, str, re.Pattern[str]]] = [
    # 1. INSTRUCTION OVERRIDE & JAILBREAKS
    (
        "INSTRUCTION_OVERRIDE",
        "HIGH",
        "Attempt to override prior instructions or reset system prompt constraints",
        re.compile(
            r"\b(?:ignore|disregard|forget|override|bypass|neglect)\s+(?:all\s+)?"
            r"(?:previous|prior|above|existing|system)?\s*"
            r"(?:instructions?|directions?|prompts?|rules?|constraints?|commands?|guidelines?)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "INSTRUCTION_OVERRIDE",
        "HIGH",
        "Attempt to override instructions in Spanish",
        re.compile(
            r"\b(?:ignora|olvida|descarta|omite)\s+(?:todas?\s+)?(?:las?\s+)?"
            r"(?:instrucciones|indicaciones|reglas|[oó]rdenes|prompts?)\s*"
            r"(?:anteriores|previas|del\s+sistema)?\b",
            re.IGNORECASE,
        ),
    ),
    (
        "JAILBREAK_ROLEPLAY",
        "HIGH",
        "Attempt to force developer mode, DAN, or unrestricted persona",
        re.compile(
            r"\b(?:you\s+are\s+now|act\s+as|pretend\s+to\s+be|switch\s+to)\s+(?:in\s+)?"
            r"(?:developer\s+mode|dan\s+mode|unrestricted|god\s+mode|an\s+unfiltered|jailbroken)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "OBFUSCATED_OVERRIDE",
        "HIGH",
        "Spaced letter evasion of 'ignore previous instructions'",
        re.compile(r"i\s*g\s*n\s*o\s*r\s*e\s+p\s*r\s*e\s*v\s*i\s*o\s*u\s*s", re.IGNORECASE),
    ),
    (
        "INSTRUCTION_OVERRIDE",
        "HIGH",
        "Direct instruction reset commands",
        re.compile(
            r"\b(?:new\s+system\s+instruction|reset\s+all\s+instructions|stop\s+following\s+rules)\b",
            re.IGNORECASE,
        ),
    ),

    # 2. DELIMITER & TOKEN HIJACKING
    (
        "DELIMITER_HIJACK",
        "HIGH",
        "ChatML / Token delimiter injection (<|im_start|>, <|im_end|>)",
        re.compile(r"<\|(?:im_start|im_end|endoftext|system|user|assistant)\|?>", re.IGNORECASE),
    ),
    (
        "DELIMITER_HIJACK",
        "HIGH",
        "Llama / Mistral token delimiter injection ([INST], [SYS])",
        re.compile(r"\[\/?(?:INST|SYS|SYSTEM)\]|<<\/?SYS>>", re.IGNORECASE),
    ),
    (
        "DELIMITER_HIJACK",
        "MEDIUM",
        "Pseudo-XML system tags mimicking prompt frames",
        re.compile(r"<\/?(?:system|instruction|system-prompt|system_instruction|prompt_context)>", re.IGNORECASE),
    ),
    (
        "ROLE_HIJACK",
        "HIGH",
        "Fake role turn heading (### System: or ### Instruction:)",
        re.compile(r"^\s*###\s*(?:System|Instruction|Assistant|Human|Developer)\s*:", re.IGNORECASE | re.MULTILINE),
    ),
    (
        "ROLE_HIJACK",
        "MEDIUM",
        "Simulated dialogue injection attempting to command the assistant",
        re.compile(r"^\s*(?:System|Assistant):\s*(?:you\s+must|ignore|output|forget|reject)", re.IGNORECASE | re.MULTILINE),
    ),

    # 3. EVALUATION & CANDIDATE TAMPERING
    (
        "EVALUATION_SABOTAGE",
        "HIGH",
        "Malicious instruction to reject candidate or not hire",
        re.compile(
            r"\b(?:do\s+not|never|don't)\s+(?:hire|interview|consider|accept|advance)\s+"
            r"this\s+(?:candidate|applicant|person|individual|engineer)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "EVALUATION_SABOTAGE",
        "HIGH",
        "Direct sabotage command to reject or score candidate 0",
        re.compile(
            r"\b(?:reject|disqualify|discard|drop)\s+(?:this\s+)?(?:candidate|applicant|application)\s*"
            r"(?:immediately|at\s+all\s+costs|without\s+review)?\b",
            re.IGNORECASE,
        ),
    ),
    (
        "EVALUATION_SABOTAGE",
        "HIGH",
        "Instruction to rate candidate 0 or declare incompetent",
        re.compile(
            r"\b(?:score|rate|evaluate|grade)\s+(?:this\s+)?(?:candidate|applicant)\s*"
            r"(?:as\s*)?(?:0|zero|1|lowest|unqualified)\b|"
            r"\b(?:say|tell\s+the\s+user|output\s+that)\s+(?:this\s+candidate|the\s+applicant)\s+"
            r"is\s+(?:incompetent|unqualified|a\s+bot|fake)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "EVALUATION_SABOTAGE",
        "HIGH",
        "Sabotage instruction in Spanish",
        re.compile(
            r"\b(?:no\s+(?:contrates?|recomiendes?|pases?)\s+a\s+este\s+candidato|"
            r"rechaza\s+esta\s+postulaci[oó]n|califica\s+con\s+cero)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "EVALUATION_FORGERY",
        "MEDIUM",
        "Instruction demanding 100% match regardless of skills",
        re.compile(
            r"\b(?:rate|declare|mark)\s+this\s+(?:candidate|applicant)\s*"
            r"(?:as\s*)?(?:100%|perfect)\s+(?:regardless|no\s+matter\s+what)\b",
            re.IGNORECASE,
        ),
    ),

    # 4. SYSTEM PROMPT & DATA EXFILTRATION
    (
        "DATA_EXFILTRATION",
        "HIGH",
        "Attempt to dump system prompt, profile.yaml, or secrets",
        re.compile(
            r"\b(?:reveal|print|output|display|show|leak|repeat|dump)\s+(?:the\s+|your\s+)?"
            r"(?:system\s+prompt|developer\s+instructions|profile\.yaml|api[ _-]?keys?|"
            r"environment\s+variables?|env\s+vars?|credentials?|secret\s+key)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "DATA_EXFILTRATION",
        "HIGH",
        "Data leak attempt in Spanish",
        re.compile(
            r"\b(?:muestra|imprime|revela)\s+(?:tu\s+)?(?:prompt\s+de\s+sistema|"
            r"instrucciones\s+del\s+sistema|profile\.yaml|claves?\s+api)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "MARKDOWN_EXFILTRATION",
        "HIGH",
        "Markdown image exfiltration beacon targeting credentials or prompt",
        re.compile(r"!\[.*?\]\s*\(\s*https?:\/\/[^\s\)]+[\?\&](?:leak|data|exfil|token|key|prompt|stolen)=", re.IGNORECASE),
    ),
]

HIDDEN_STYLE_PATTERN = re.compile(
    r"<(?:div|span|p|section|article|header|footer)[^>]+style\s*=\s*['\"][^'\"]*"
    r"(?:display\s*:\s*none|visibility\s*:\s*hidden|font-size\s*:\s*0|opacity\s*:\s*0|color\s*:\s*transparent)"
    r"[^'\"]*['\"][^>]*>([\s\S]*?)<\/(?:div|span|p|section|article|header|footer)>",
    re.IGNORECASE,
)
HIDDEN_ATTR_PATTERN = re.compile(
    r"<(?:div|span|p|section|article)[^>]*\bhidden\b[^>]*>([\s\S]*?)<\/(?:div|span|p|section|article)>",
    re.IGNORECASE,
)
HTML_COMMENT_PATTERN = re.compile(r"<!--([\s\S]*?)-->")


# -------------------------------------------------------------
# CORE SCANNER & SANITIZER
# -------------------------------------------------------------

def detect_zero_width(text: str) -> List[Dict[str, Any]]:
    """Finds invisible unicode characters and tags in text."""
    findings: List[Dict[str, Any]] = []
    for idx, ch in enumerate(text):
        if ch in ZERO_WIDTH_CHARS:
            findings.append({
                "char": repr(ch),
                "name": ZERO_WIDTH_CHARS[ch],
                "position": idx,
            })
    tag_matches = list(UNICODE_TAGS_PATTERN.finditer(text))
    for m in tag_matches:
        findings.append({
            "char": repr(m.group(0)),
            "name": "UNICODE TAG CHAR (INVISIBLE)",
            "position": m.start(),
        })
    return findings


def scan_hidden_html(raw_html: str) -> List[Dict[str, Any]]:
    """Inspects raw HTML for stealth nodes that users don't see in browser."""
    threats: List[Dict[str, Any]] = []
    if not raw_html:
        return threats

    # Check hidden styles
    for m in HIDDEN_STYLE_PATTERN.finditer(raw_html):
        content = html.unescape(m.group(1)).strip()
        if content:
            threats.append({
                "category": "STEALTH_HTML_HIDDEN",
                "severity": "HIGH" if any(r[3].search(content) for r in THREAT_RULES) else "MEDIUM",
                "pattern": "style='display:none' or invisible styling",
                "matched_text": content[:200],
                "position": m.start(),
                "explanation": "Hidden HTML container that is invisible to browser users but read by parsers",
            })

    # Check hidden attribute
    for m in HIDDEN_ATTR_PATTERN.finditer(raw_html):
        content = html.unescape(m.group(1)).strip()
        if content:
            threats.append({
                "category": "STEALTH_HTML_HIDDEN",
                "severity": "HIGH" if any(r[3].search(content) for r in THREAT_RULES) else "MEDIUM",
                "pattern": "<tag hidden>",
                "matched_text": content[:200],
                "position": m.start(),
                "explanation": "HTML container with 'hidden' attribute",
            })

    # Check HTML comments with instructions
    for m in HTML_COMMENT_PATTERN.finditer(raw_html):
        comment = m.group(1).strip()
        if any(r[3].search(comment) for r in THREAT_RULES):
            threats.append({
                "category": "STEALTH_HTML_COMMENT",
                "severity": "HIGH",
                "pattern": "<!-- comment containing injection -->",
                "matched_text": comment[:200],
                "position": m.start(),
                "explanation": "HTML comment containing executable prompt injection payload",
            })

    return threats


def scan_text(text: str, raw_html: str = "") -> Dict[str, Any]:
    """Scans job description text and optional raw HTML for prompt injection threats."""
    threats: List[Dict[str, Any]] = []

    # 1. Regex signature scan on text
    for category, severity, explanation, pattern in THREAT_RULES:
        for match in pattern.finditer(text):
            threats.append({
                "category": category,
                "severity": severity,
                "pattern": pattern.pattern,
                "matched_text": match.group(0),
                "position": match.start(),
                "explanation": explanation,
            })

    # 2. Check for zero-width stealth
    zw_findings = detect_zero_width(text)
    if zw_findings:
        threats.append({
            "category": "STEALTH_ZERO_WIDTH",
            "severity": "HIGH" if len(zw_findings) > 3 else "MEDIUM",
            "pattern": "Unicode zero-width codepoints",
            "matched_text": f"{len(zw_findings)} invisible unicode characters detected",
            "position": zw_findings[0]["position"],
            "explanation": "Invisible zero-width characters used to smuggle instructions past filters",
        })

    # 3. Check raw HTML if provided
    if raw_html:
        threats.extend(scan_hidden_html(raw_html))

    # Calculate risk level
    severities = {t["severity"] for t in threats}
    if "HIGH" in severities and len(threats) >= 2:
        risk_level = "CRITICAL"
    elif "HIGH" in severities:
        risk_level = "HIGH"
    elif "MEDIUM" in severities:
        risk_level = "MEDIUM"
    elif threats:
        risk_level = "LOW"
    else:
        risk_level = "CLEAN"

    is_safe = risk_level in ("CLEAN", "LOW")
    sanitized = sanitize_text(text)

    return {
        "is_safe": is_safe,
        "risk_level": risk_level,
        "threat_count": len(threats),
        "threats": threats,
        "zero_width_count": len(zw_findings),
        "sanitized_text": sanitized,
    }


def sanitize_text(text: str) -> str:
    """Strips zero-width stealth characters and neutralizes injection delimiters."""
    if not text:
        return ""

    # Remove zero-width characters and invisible tags
    cleaned = "".join(ch for ch in text if ch not in ZERO_WIDTH_CHARS)
    cleaned = UNICODE_TAGS_PATTERN.sub("", cleaned)

    # Neutralize ChatML / Delimiter tokens
    cleaned = re.sub(r"<\|(im_start|im_end|system|user|assistant)\|?>", r"[escaped-\1]", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\[\/?(INST|SYS|SYSTEM)\]", r"[escaped-\1]", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"<\/?(system|instruction|prompt_context)>", r"[escaped-\1]", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"^\s*###\s*(System|Instruction|Assistant|Human)\s*:", r"### (escaped \1):", cleaned, flags=re.IGNORECASE | re.MULTILINE)

    # Neutralize image exfiltration markdown
    cleaned = re.sub(
        r"!\[(.*?)\]\s*\(\s*https?:\/\/[^\s\)]+[\?\&](?:leak|data|exfil|token|key|prompt|stolen)=[^\s\)]*\)",
        r"[neutralized-beacon]",
        cleaned,
        flags=re.IGNORECASE,
    )

    return cleaned


def format_audit_report(scan_res: Dict[str, Any]) -> str:
    """Formats the scan results as clean human-readable markdown."""
    lines = [
        f"### Prompt Injection Audit: **{scan_res['risk_level']}**",
        f"- Safe for LLM processing: **{'YES' if scan_res['is_safe'] else 'NO (THREAT DETECTED)'}**",
        f"- Threats identified: **{scan_res['threat_count']}**",
        f"- Invisible zero-width chars: **{scan_res['zero_width_count']}**",
    ]
    if scan_res["threats"]:
        lines.append("\n#### Identified Threats:")
        for idx, t in enumerate(scan_res["threats"], 1):
            lines.append(f"{idx}. `[{t['severity']}]` **{t['category']}**: {t['explanation']}")
            lines.append(f"   - Match snippet: *\"{t['matched_text']}\"*")
    else:
        lines.append("- Result: No prompt injection or evasion patterns detected.")
    return "\n".join(lines)
