from __future__ import annotations

import re
from dataclasses import dataclass

from .evidence import EvidenceSegment
from .forms import FormItem


STOPWORDS = {
    "a", "about", "all", "an", "and", "any", "are", "as", "at", "be", "been", "by", "did",
    "do", "each", "for", "from", "give", "have", "if", "in", "is", "it", "list", "name", "of",
    "on", "or", "please", "provide", "said", "state", "that", "the", "their", "there", "these",
    "this", "to", "was", "were", "what", "when", "where", "which", "who", "with", "you", "your",
    "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "time",
}

CONCEPTS = {
    "injury": {"injury", "injuries", "diagnosis", "diagnosed", "condition", "pain", "fracture", "strain"},
    "treatment": {"treatment", "treated", "therapy", "physician", "doctor", "hospital", "medical", "visit"},
    "disability": {"disability", "disabled", "impairment", "restriction", "limitations", "capacity"},
    "expense": {"expense", "cost", "charge", "bill", "paid", "payment", "amount", "balance"},
    "employment": {"employer", "employment", "job", "occupation", "wage", "salary", "work", "hours"},
    "income": {"income", "earnings", "salary", "wage", "bonus", "commission", "tips", "overtime"},
    "address": {"address", "residence", "located", "location", "street", "avenue", "road", "drive"},
    "vehicle": {"vehicle", "automobile", "car", "truck", "driver", "operator", "license"},
    "incident": {"incident", "accident", "collision", "occurrence", "scene"},
    "statement": {"statement", "recorded", "recording", "interview", "witness", "testimony"},
    "insurance": {"insurance", "insurer", "policy", "coverage", "medicare", "medicaid"},
    "property": {"property", "real estate", "mortgage", "rent", "rental", "owner", "ownership"},
    "business": {"business", "self-employed", "corporation", "partnership", "llc", "accountant"},
    "benefits": {"benefit", "benefits", "compensation", "social security", "ssi", "ssd"},
    "trust": {"trust", "trustee", "beneficiary", "settlor", "distribution"},
    "lawsuit": {"lawsuit", "claim", "action", "court", "docket", "settlement"},
}

DISTINCTIVE_SINGLE_TERMS = {
    "birth", "license", "diagnosis", "diagnosed", "fracture", "strain", "overtime",
    "surveillance", "alcohol", "alcoholic", "drugs", "medications", "employer", "earnings",
    "income", "wage", "salary", "mortgage", "trust", "trustee", "inherit", "inheritance",
}
CONFIRMATION_WORDS = {
    "aware", "claim", "do you", "have you", "are you", "did you", "expect", "presently", "relationship",
}
TOKEN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)?")
MONEY = re.compile(r"\$\s?\d[\d,]*(?:\.\d{2})?")
DATE = re.compile(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b|\b(?:19|20)\d{2}\b")
PERCENT = re.compile(r"\b\d+(?:\.\d+)?\s*(?:%|percent)\b", re.I)
HOURS = re.compile(r"\b\d+(?:\.\d+)?\s*hours?\b", re.I)


@dataclass(frozen=True)
class Candidate:
    segment: EvidenceSegment
    score: float
    matched_terms: tuple[str, ...]

    def to_dict(self) -> dict:
        return {
            "segment_id": self.segment.segment_id,
            "source_id": self.segment.source_id,
            "filename": self.segment.filename,
            "page": self.segment.page,
            "quote": self.segment.text,
            "score": round(self.score, 3),
            "matched_terms": list(self.matched_terms),
        }


def _tokens(text: str) -> set[str]:
    return {token for token in TOKEN.findall(text.lower()) if len(token) > 2 and token not in STOPWORDS}


def query_terms(item: FormItem) -> tuple[set[str], set[str], set[str]]:
    primary_text = item.text.lower()
    context_text = item.prompt.lower()
    primary = _tokens(primary_text)
    context = _tokens(context_text) - primary
    expanded: set[str] = set()
    for trigger, expansion in CONCEPTS.items():
        if trigger in primary or trigger in primary_text:
            expanded.update(expansion)
    return primary, context, expanded - primary - context


def rank_evidence(item: FormItem, segments: list[EvidenceSegment], limit: int = 5) -> list[Candidate]:
    primary, context, expanded = query_terms(item)
    terms = primary | context | expanded
    if not terms or not segments:
        return []
    candidates: list[Candidate] = []
    for segment in segments:
        tokens = _tokens(segment.text)
        matched = tokens & terms
        if not matched:
            continue
        matched_primary = tokens & primary
        matched_context = tokens & context
        matched_expanded = tokens & expanded
        if not matched_primary and len(matched_expanded) < 2:
            continue
        score = 2.0 * len(matched_primary) + 0.45 * len(matched_context) + 1.0 * len(matched_expanded)
        lowered = segment.text.lower()
        phrase_boost = False
        if "home address" in item.text.lower() and ("home address" in lowered or "resides at" in lowered):
            score += 3.0
            phrase_boost = True
        if "residence" in (item.text + item.prompt).lower() and ("home address" in lowered or "resides at" in lowered):
            score += 3.0
            phrase_boost = True
        if "employer" in item.text.lower() + item.prompt.lower() and "employer" in lowered:
            score += 2.0
            phrase_boost = True
        if segment.kind == "heading":
            score *= 0.35
        if len(matched) == 1 and not phrase_boost and not (matched_primary & DISTINCTIVE_SINGLE_TERMS):
            continue
        candidates.append(Candidate(segment, score, tuple(sorted(matched))))
    candidates.sort(key=lambda candidate: (-candidate.score, candidate.segment.source_id, candidate.segment.page))
    return candidates[:limit]


def _potential_conflict(item: FormItem, candidates: list[Candidate]) -> bool:
    question = f"{item.prompt} {item.text}".lower()
    patterns = []
    if any(word in question for word in {"income", "earnings", "salary", "wage", "amount", "cost", "paid", "value"}):
        patterns.append(MONEY)
    if "percent" in question or "percentage" in question:
        patterns.append(PERCENT)
    if "hour" in question:
        patterns.append(HOURS)
    if "date" in question or "when" in question:
        patterns.append(DATE)
    if not patterns or len(candidates) < 2:
        return False
    values_by_source: dict[str, set[str]] = {}
    for candidate in candidates[:4]:
        values = {value.lower().replace(" ", "") for pattern in patterns for value in pattern.findall(candidate.segment.text)}
        if values:
            values_by_source.setdefault(candidate.segment.source_id, set()).update(values)
    observed = set().union(*values_by_source.values()) if values_by_source else set()
    return len(values_by_source) > 1 and len(observed) > 1


def _verified_draft(item: FormItem, candidates: list[Candidate]) -> tuple[str, list[Candidate]] | None:
    """Conservative pilot: draft only explicit, respondent-attributed weekly wages.

    No inferred subject, time period, arithmetic, or negative answers. This is
    intentionally narrow until identity and temporal fact binding are implemented.
    """
    if item.item_id != "207-3-c":
        return None
    pattern = re.compile(
        r"\brespondent\s+(?:has|earns|receives|reports|reported|is paid)\s+"
        r"(?:a\s+)?(?:weekly\s+)?(?:gross\s+|net\s+)?(?:wages?|income|salary)?\s*"
        r"(?:of\s+)?(\$\s*\d[\d,]*(?:\.\d{2})?)\s*(?:per week|weekly|/week)\b",
        re.I,
    )
    hits = []
    for candidate in candidates:
        match = pattern.search(candidate.segment.text)
        if match:
            hits.append((match.group(1).replace(" ", ""), candidate))
    if not hits or len({value for value, _ in hits}) != 1:
        return None
    value, source = hits[0]
    return f"The record states weekly income of {value}. [Source: {source.segment.filename}, p. {source.segment.page}; verify responding party and current amount.]", [source]


def build_answer(item: FormItem, candidates: list[Candidate]) -> dict:
    if not candidates:
        question = f"{item.prompt} {item.text}".lower()
        status = "CLIENT_CONFIRMATION_REQUIRED" if any(word in question for word in CONFIRMATION_WORDS) else "NO_RESPONSIVE_EVIDENCE"
        return {"status": status, "answer": "", "evidence": []}
    conflict = _potential_conflict(item, candidates)
    citations = []
    seen: set[str] = set()
    for candidate in candidates[:3]:
        quote = candidate.segment.text.strip()
        if quote in seen:
            continue
        seen.add(quote)
        citations.append(candidate.to_dict())
    draft = None if conflict else _verified_draft(item, candidates)
    if draft:
        text, sources = draft
        return {"status": "DRAFTED_FROM_EVIDENCE", "answer": text,
                "evidence": [source.to_dict() for source in sources]}
    return {
        "status": "POTENTIAL_CONFLICT" if conflict else "REVIEW_REQUIRED",
        "answer": "",
        "evidence": citations,
    }
