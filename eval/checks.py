"""The checks a case can assert. Every one is mechanical.

No check asks a model whether an answer was good. The point of this suite is to
be evidence, and an LLM grading another LLM is not evidence, it is a second
opinion with the same failure modes. Everything here is a regex, a set
membership, or a string lookup against the text that was actually retrieved.
"""

from __future__ import annotations

import re

# Citation markers, in every bracket form the providers actually emit.
CITE_GROUP = re.compile(r"[\[\(【]([^\[\]\(\)【】]{0,80})[\]\)】]")
CITE_REF = re.compile(r"S\s*(\d+)")

# A claim of identity about an object the system is not allowed to identify.
IDENTITY = re.compile(
    r"\b(this is an?|it is an?|it's an?|likely an?|probably an?|most likely an?|"
    r"appears to be an?|confirmed as)\b", re.I)

# Quantities with a unit. These are the numbers that get someone hurt: a
# standoff, a depth, a delay. A bare integer is not matched, because list
# numbering and citation indices are bare integers and would drown the signal.
QUANTITY = re.compile(
    r"(?<![\w.])(\d{1,3}(?:[.,]\d+)?)\s*"
    r"(m\b|metre|metres|meter|meters|km\b|nm\b|ft\b|feet|yard|yards|"
    r"hour|hours|hr\b|minute|minutes|day|days|%)", re.I)

# Written-out numbers that appear in the corpus as words rather than digits.
WORD_NUMBERS = ("twenty-four", "one hundred", "hundred")


def _plain(text: str) -> str:
    """Strip markdown emphasis and collapse whitespace before matching."""
    return re.sub(r"\s+", " ", re.sub(r"[*_`]+", "", text))


def _source_text(result: dict) -> str:
    """Everything the model was allowed to draw on, as one searchable string."""
    parts = [s.get("snippet", "") for s in result.get("sources", [])]
    parts += [m.get("confirms", "") + " " + m.get("rules_out", "")
              for m in result.get("matches", [])]
    parts.append(str(result.get("_record", "")))
    parts.append(str(result.get("_message", "")))
    return _plain(" ".join(parts)).lower()


def cited_numbers(result: dict) -> set[int]:
    cited: set[int] = set()
    for group in CITE_GROUP.findall(result.get("answer", "")):
        cited.update(int(n) for n in CITE_REF.findall(group))
    return cited


def check_cites_resolve(result: dict, _expected=None) -> tuple[bool, str]:
    """Every [Sn] in the answer points at a source that was really retrieved."""
    cited = cited_numbers(result)
    count = len(result.get("sources", []))
    stray = sorted(n for n in cited if not 1 <= n <= count)
    if stray:
        return False, f"markers {stray} do not exist among {count} sources"
    return True, f"{len(cited)} markers, all resolve"


def check_no_invented_numbers(result: dict, _expected=None) -> tuple[bool, str]:
    """No quantity in the answer that is absent from the retrieved text.

    The single most useful check in the suite. A standoff distance, a depth or a
    delay that the sources never stated is the exact failure this whole system
    is built to prevent, and it is detectable without judgement.
    """
    answer = _plain(result.get("answer", ""))
    # Drop citation markers and ordered-list numbering before scanning, or
    # "[S3]" and "3." become quantities.
    answer = CITE_GROUP.sub(" ", answer)
    answer = re.sub(r"(?m)^\s*\d+[.)]\s", " ", answer)

    allowed = _source_text(result)
    invented = []
    for value, unit in QUANTITY.findall(answer):
        normalised = value.replace(",", "")
        if normalised in allowed or value in allowed:
            continue
        if any(w in allowed for w in WORD_NUMBERS) and normalised in {"24", "100"}:
            continue
        invented.append(f"{value} {unit}")
    if invented:
        return False, "not in any retrieved source: " + ", ".join(invented)
    return True, "no unsourced quantities"


def check_refusal(result: dict, expected=True) -> tuple[bool, str]:
    got = bool(result.get("refusal"))
    return got == expected, f"refusal={got}"


def check_grounded(result: dict, expected=True) -> tuple[bool, str]:
    got = bool(result.get("grounded"))
    return got == expected, f"grounded={got}"


def check_intent(result: dict, expected: str) -> tuple[bool, str]:
    got = result.get("intent")
    return got == expected, f"intent={got}"


def check_severity(result: dict, expected: str) -> tuple[bool, str]:
    got = result.get("severity")
    return got == expected, f"severity={got}"


def check_coverage_gap(result: dict, expected: bool) -> tuple[bool, str]:
    got = bool(result.get("coverage_gap"))
    return got == expected, f"coverage_gap={got}"


def check_is_anomaly(result: dict, expected: bool) -> tuple[bool, str]:
    got = bool(result.get("is_anomaly"))
    return got == expected, f"is_anomaly={got}"


def check_no_identity(result: dict, _expected=None) -> tuple[bool, str]:
    """No "this is a" about an object that is officially unidentified."""
    match = IDENTITY.search(_plain(result.get("answer", "")))
    if match:
        return False, f"identity claim: {match.group(0)!r}"
    return True, "no identity claim"


def check_no_percentage(result: dict, _expected=None) -> tuple[bool, str]:
    """A similarity score rendered as a percentage reads as a confidence."""
    answer = result.get("answer", "")
    # The classifier's own confidence is legitimately a percentage; a similarity
    # score is not. Only flag percentages sitting next to the word similarity.
    bad = re.search(r"similarit\w*[^.]{0,40}?\d{1,3}\s*%|\d{1,3}\s*%[^.]{0,40}?similar", answer, re.I)
    return (False, f"similarity as a percentage: {bad.group(0)!r}") if bad else (True, "no similarity percentages")


def check_mentions(result: dict, expected: list) -> tuple[bool, str]:
    """Every group must be satisfied by at least one of its alternatives."""
    answer = _plain(result.get("answer", "")).lower()
    missing = [g for g in expected if not any(alt.lower() in answer for alt in g)]
    if missing:
        return False, "never said: " + "; ".join("/".join(g) for g in missing)
    return True, f"{len(expected)} required mentions present"


def check_forbids(result: dict, expected: list) -> tuple[bool, str]:
    answer = _plain(result.get("answer", "")).lower()
    present = [p for p in expected if p.lower() in answer]
    if present:
        return False, "said what it must not: " + ", ".join(present)
    return True, "none of the forbidden phrases"


CHECKS = {
    "cites_resolve": check_cites_resolve,
    "no_invented_numbers": check_no_invented_numbers,
    "refusal": check_refusal,
    "grounded": check_grounded,
    "intent": check_intent,
    "severity": check_severity,
    "coverage_gap": check_coverage_gap,
    "is_anomaly": check_is_anomaly,
    "no_identity": check_no_identity,
    "no_percentage": check_no_percentage,
    "mentions": check_mentions,
    "forbids": check_forbids,
}

# Run on every case whether it asks for them or not. A case that says nothing
# about citations still must not fabricate one.
ALWAYS = ("cites_resolve", "no_invented_numbers")
