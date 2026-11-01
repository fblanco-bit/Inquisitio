from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass
from typing import Iterable
from collections import defaultdict
from datetime import datetime
from dateutil import parser as date_parser
try:
    from rapidfuzz import fuzz
except ImportError:  # Keep source checkouts runnable when only bundled Mac wheels exist.
    from difflib import SequenceMatcher

    class _Fuzz:
        @staticmethod
        def ratio(left: str, right: str) -> float:
            return SequenceMatcher(None, left, right).ratio() * 100

        @staticmethod
        def token_set_ratio(left: str, right: str) -> float:
            left_tokens = " ".join(sorted(set(left.split())))
            right_tokens = " ".join(sorted(set(right.split())))
            return SequenceMatcher(None, left_tokens, right_tokens).ratio() * 100

    fuzz = _Fuzz()

from .binding import Candidate, rank_evidence
from .evidence import EvidenceSegment
from .forms import FormItem


ENGINE_STATUSES = {
    "EMPTY",
    "DRAFT",
    "EDITED",
    "APPROVED",
    "POTENTIAL_CONFLICT",
    "REQUIRES_CLIENT",
}
WORKFLOW_STATUSES = ENGINE_STATUSES


@dataclass(frozen=True)
class CaseContext:
    plaintiff: str
    defendant: str
    responding_party_role: str
    responding_party: str
    interrogating_party: str
    response_date: str


@dataclass(frozen=True)
class Requirement:
    question_id: str
    wording: str
    subject: str
    attributes: tuple[str, ...]
    time_scope: str
    expected_type: str
    conditional_attribute: str = ""
    conditional_value: str = "true"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class Fact:
    fact_id: str
    subject: str
    attribute: str
    value: str
    unit: str
    period: str
    source_id: str
    filename: str
    document_sha256: str
    page: int
    quote: str
    segment_id: str
    evidence_classification: str
    verification_status: str
    original_value: str = ""
    normalized_value: str = ""
    extraction_method: str = "pdfplumber"
    ocr_sourced: bool = False
    confidence: float = 1.0
    attribution_quote: str = ""
    attribution_segment_id: str = ""
    source_segment_ids: tuple[str, ...] = ()
    record_group: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


_ITEM_REQUIREMENTS: dict[str, tuple[str, ...]] = {
    "202-1-a": ("full_name",),
    "202-1-b": ("date_of_birth",),
    "202-1-c": ("drivers_license",),
    "202-1-d": ("home_address",),
    "202-1-e": ("business_address",),
    "202-2": ("incident_injury",),
    "202-3": ("first_treatment_date", "first_treatment_provider", "first_treatment_location"),
    "202-9": ("current_treatment",),
    "202-10": ("current_treatment_provider",),
    "202-11": ("present_disability",),
    "202-12": ("present_disability_nature",),
    "202-13": ("permanent_disability",),
    "202-14-a": ("permanent_disability_body_part",),
    "202-14-b": ("permanent_disability_limitations",),
    "202-14-c": ("permanent_disability_percentage",),
    "202-14-d": ("permanent_disability_provider",),
    "202-14-e": ("permanent_disability_date",),
    "202-17": ("incident_expense",),
    "202-23-a": ("incident_employer_name", "incident_employer_address"),
    "202-23-b": ("incident_occupation", "incident_job_duties"),
    "202-23-c": ("historical_gross_weekly_income",),
    "202-23-d": ("work_resumption_date",),
    "202-23-e": ("lost_income", "lost_income_calculation"),
    "202-23-f": ("lost_work_dates",),
    "202-24": ("earning_capacity_impairment",),
    "202-29": ("incident_statement",),
    "202-30": ("incident_witness",),
    "202-36": ("workers_comp_claim",),
    "202-37": ("workers_comp_benefits",),
    "207-1-a": ("home_address",),
    "207-1-b": ("residence_type",),
    "207-1-c": ("residence_owner",),
    "207-1-d": ("residence_owner_relationship",),
    "207-1-e": ("residence_start_date",),
    "207-2-a": ("household_adults", "household_relationships"),
    "207-2-b": ("household_contributions",),
    "207-3-a": ("employer_name", "employer_address", "employment_status"),
    "207-3-b": ("pay_basis",),
    "207-3-c": ("current_gross_weekly_income",),
    "207-3-d": ("current_weekly_hours",),
    "207-3-e": ("overtime_availability", "overtime_hours", "overtime_pay"),
    "207-3-f": ("bonus_income",),
    "207-3-g": ("payroll_deductions",),
    "207-3-h": ("second_employment",),
    "207-4-a": ("business_structure", "business_name", "business_role"),
    "207-4-b": ("business_people",),
    "207-4-c": ("business_tax_filing",),
    "207-4-d": ("business_work",),
    "207-4-e": ("self_employed_weekly_hours",),
    "207-4-f": ("self_employed_hourly_income",),
    "207-4-g": ("business_expenses",),
    "207-4-h": ("business_payment_method",),
    "207-4-i": ("business_customers",),
    "207-4-j": ("business_bank",),
    "207-4-k": ("business_employees",),
    "207-4-l": ("business_records", "accountant"),
    "207-5": ("employment_history",),
    "207-6-a": ("disability_start_date",),
    "207-6-b": ("disability_duration",),
    "207-6-c": ("disability_doctor",),
    "207-6-d": ("disability_work_capacity",),
    "207-6-e": ("disability_percentage",),
    "207-6-f": ("disability_cause",),
    "207-6-g": ("children_since_disability",),
    "207-7-a": ("disability_benefit_application",),
    "207-7-b": ("disability_benefit_decision",),
    "207-7-c": ("disability_benefit_appeal",),
    "207-7-d": ("state_assistance",),
    "207-7-e": ("state_benefit",),
    "207-8-a": ("pending_lawsuit_type",),
    "207-8-b": ("pending_lawsuit_lawyer",),
    "207-8-c": ("pending_lawsuit_recovery",),
    "207-8-d": ("settlement_statement",),
    "207-9-a": ("expected_inheritance_source",),
    "207-9-b": ("expected_inheritance",),
    "207-9-c": ("estate_contact",),
    "207-10": ("money_held_for_respondent",),
    "207-11-a": ("rental_property_type",),
    "207-11-b": ("rental_property_location", "rental_ownership_interest"),
    "207-11-c": ("rental_income",),
    "207-11-d": ("rental_expenses",),
    "207-11-e": ("rental_loan",),
    "207-12-a": ("trust_details",),
    "207-12-b": ("trust_distributions",),
}

_CONDITIONS: dict[str, tuple[str, str]] = {
    "202-10": ("current_treatment", "true"),
    "202-12": ("present_disability", "true"),
    "202-14-a": ("permanent_disability", "true"),
    "202-14-b": ("permanent_disability", "true"),
    "202-14-c": ("permanent_disability", "true"),
    "202-14-d": ("permanent_disability", "true"),
    "202-14-e": ("permanent_disability", "true"),
}
for _label in "abcdefghijkl":
    _CONDITIONS[f"207-4-{_label}"] = ("self_employed", "true")
for _label in "abcdefg":
    _CONDITIONS[f"207-6-{_label}"] = ("unable_to_work_disability", "true")
for _label in "abcde":
    _CONDITIONS[f"207-11-{_label}"] = ("owns_rental_property", "true")
for _label in "ab":
    _CONDITIONS[f"207-12-{_label}"] = ("trust_party", "true")

_ATTRIBUTE_LABELS = {name: name.replace("_", " ") for values in _ITEM_REQUIREMENTS.values() for name in values}
_MULTI_VALUE_ATTRIBUTES = {
    "incident_injury", "incident_expense", "incident_witness", "household_adults",
    "household_relationships", "household_contributions", "employment_history", "business_people",
    "business_customers", "business_employees", "state_benefit",
}
_RELIABLE_CLASSES = {"THIRD_PARTY_RECORD", "SWORN_DECLARATION", "JUDICIAL_FINDING", "PARTY_RECORD"}


# Every selected interrogatory/subpart has explicit targets. The selected form
# supplies the target set to extraction; unrelated facts cannot populate it.
_ITEM_REQUIREMENTS.update({
    '202-1-a': ('full_name', 'other_names'),
    '202-1-f': ('vehicle_owner', 'vehicle_owner_address'),
    '202-4': ('hospital_name', 'hospital_location', 'hospital_admission', 'hospital_discharge'),
    '202-5': ('treating_provider', 'provider_address'),
    '202-6': ('last_treatment_date', 'last_treatment_provider'),
    '202-7': ('recovery_status', 'full_recovery_date'),
    '202-8': ('present_complaints',),
    '202-10': ('current_treatment_provider', 'current_provider_address'),
    '202-15': ('home_bed_confinement_dates',),
    '202-16': ('medical_reports_received', 'anticipated_medical_witnesses'),
    '202-18': ('expense_reimbursement',),
    '202-19': ('prior_related_conditions', 'prior_treatment_dates', 'prior_treatment_providers'),
    '202-23-c': ('historical_gross_weekly_income',),
    '202-23-g': ('prior_employer', 'prior_employer_history_complete'),
    '202-25': ('other_claimed_expenses', 'other_claimed_expense_amounts'),
    '202-26': ('release_beneficiary', 'release_date', 'release_consideration'),
    '202-27': ('liability_limitation_beneficiary', 'liability_limitation_date', 'liability_limitation_consideration'),
    '202-28': ('subsequent_workers_comp_claims', 'subsequent_workers_comp_claim_dates'),
    '202-33': ('preincident_alcohol_drugs',),
    '202-35': ('surveillance_material', 'surveillance_preparer', 'surveillance_dates'),
    '202-38': ('incident_phone_use',),
})
for _number, _prefix in ((20, 'prior_incident'), (21, 'subsequent_incident')):
    for _letter, _attrs in zip('abcdefghi', (
        ('date_and_manner',), ('claim',), ('claim_targets',), ('court_return_date_docket',),
        ('injuries',), ('providers',), ('treatment_dates',), ('treatment_nature',), ('disability_details',))):
        _ITEM_REQUIREMENTS[f'202-{_number}-{_letter}'] = tuple(f'{_prefix}_{a}' for a in _attrs)
for _letter, _attr in zip('abc', ('body_part', 'percentage', 'date')):
    _ITEM_REQUIREMENTS[f'202-22-{_letter}'] = (f'other_permanent_disability_{_attr}', 'other_permanent_disability_provider')
for _letter, _attr in zip('abcde', ('date', 'taker_contact', 'persons_present', 'medium', 'custodian')):
    _ITEM_REQUIREMENTS[f'202-31-{_letter}'] = (f'incident_statement_{_attr}',)
for _letter, _attr in zip('abcde', ('creator_contact', 'date', 'subject', 'number', 'type')):
    _ITEM_REQUIREMENTS[f'202-32-{_letter}'] = (f'incident_recording_{_attr}',)
for _letter, _attr in zip('abc', ('provider', 'date_time', 'results')):
    _ITEM_REQUIREMENTS[f'202-34-{_letter}'] = (f'postincident_substance_test_{_attr}',)
_ATTRIBUTE_LABELS.update({a: a.replace('_', ' ') for attrs in _ITEM_REQUIREMENTS.values() for a in attrs})
_MULTI_VALUE_ATTRIBUTES.update({
    'other_names', 'treating_provider', 'provider_address', 'current_treatment_provider',
    'current_provider_address', 'present_complaints', 'hospital_name', 'hospital_location',
    'hospital_admission', 'hospital_discharge', 'incident_statement', 'medical_reports_received',
})

_DATE = re.compile(r'\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}/\d{1,2}/\d{2,4}\b|\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?\s+\d{1,2},?\s+\d{4}\b', re.I)
_LABELS = {
    'full_name': ('operator name', 'patient name', 'full name', 'legal name', 'patient', 'name'),
    'other_names': ('other names used', 'other names', 'also known as', 'aliases'),
    'date_of_birth': ('date of birth', 'birth date', 'dob', 'born'),
    'drivers_license': ("motor vehicle operator's license number", 'operator license no.', 'operator license number', "driver's license number", 'drivers license', 'license no.', 'license number', 'license'),
    'home_address': ('home address', 'present residence', 'residence address', 'residential address', 'residence', 'address'),
    'business_address': ('business address',),
    'vehicle_owner': ('registered owner', 'vehicle owner', 'owner'),
    'vehicle_owner_address': ('registered owner address', 'vehicle owner address'),
    'employer_name': ('employer name', "employer's name", 'employer', 'company name'),
    'employer_address': ("employer's address", 'employer address'),
    'incident_occupation': ('occupation', 'job title', 'position'),
    'incident_job_duties': ('job responsibilities', 'job duties', 'duties'),
    'current_weekly_hours': ('hours per week', 'weekly hours'),
    'current_gross_weekly_income': ('current gross weekly income', 'gross weekly income', 'gross weekly pay', 'weekly gross income'),
    'historical_gross_weekly_income': ('average weekly earnings for the preceding year', 'average weekly earnings', 'historical gross weekly income'),
    'hourly_rate': ('hourly rate', 'hourly wage'),
    'pay_basis': ('pay basis', 'payment basis'),
    'employment_status': ('employment status',),
    'residence_type': ('residence type', 'property type'),
    'residence_owner': ('residence owner', 'property owner'),
    'residence_owner_relationship': ('relationship to owner',),
    'residence_start_date': ('residence start date', 'moved in'),
    'household_adults': ('household adults', 'adult household members'),
    'household_relationships': ('household relationships',),
    'household_contributions': ('household contributions',),
    'first_treatment_date': ('first treatment date',),
    'first_treatment_provider': ('first treatment provider',),
    'first_treatment_location': ('first treatment location',),
    'treating_provider': ('treating provider', 'treating physician'),
    'provider_address': ('provider address',),
    'present_complaints': ('present complaints', 'current symptoms'),
    'home_bed_confinement_dates': ('home confinement dates', 'bed confinement dates'),
    'existing_support_order': ('existing support order', 'support order'),
}
# Ordinary labels for every semantic target, not just the common aliases above.
for _attrs in _ITEM_REQUIREMENTS.values():
    for _a in _attrs:
        _LABELS.setdefault(_a, (_a.replace('_', ' '),))
_LABEL_LOOKUP = {re.sub(r'[^a-z0-9]+', ' ', label.lower()).strip(): a for a, labels in _LABELS.items() for label in labels}
_LABEL_PATTERNS = [(a, re.compile(r'^' + re.escape(label).replace(r'\ ', r'\s+') + r'(?=$|\s|:|=|_)\s*[:=_]*\s*(.*)$', re.I))
                   for a, labels in _LABELS.items() for label in labels]
_LABEL_PATTERNS.sort(key=lambda x: -len(x[1].pattern))
_INLINE = re.compile(r'(?<![A-Za-z])(' + '|'.join(re.escape(x) for x in sorted(_LABEL_LOOKUP, key=len, reverse=True)) + r')\s*:\s*', re.I)


def _inline_fields(text):
    matches = list(_INLINE.finditer(text))
    return [(_LABEL_LOOKUP[re.sub(r'[^a-z0-9]+', ' ', m[1].lower()).strip()], text[m.end():matches[i+1].start() if i+1<len(matches) else len(text)].strip(' ,;')) for i,m in enumerate(matches)]


def _clean(text: str) -> str:
    return re.sub(r'\s+', ' ', str(text)).strip(' \t\n_:;')


def _date(value: str) -> str:
    match = _DATE.search(value)
    if not match:
        return ''
    try:
        return date_parser.parse(match.group(), dayfirst=False, fuzzy=False, default=datetime(1900, 1, 1)).date().isoformat()
    except (ValueError, OverflowError):
        return ''


def _person_tokens(name: str) -> list[str]:
    name = re.sub(r'\b(?:Mr|Mrs|Ms|Dr)\.?\s+', '', name, flags=re.I)
    if ',' in name and not re.search(r',\s*(?:M\.?D|PT|Inc|LLC)\b', name, re.I):
        last, first = name.split(',', 1)
        name = first + ' ' + last
    return re.findall(r"[a-z]+(?:[-'][a-z]+)*", name.lower())


def _same_person(name: str, canonical: str) -> bool:
    a, b = _person_tokens(name), _person_tokens(canonical)
    if not a or not b or len(a) < 2 or len(b) < 2:
        return False
    if fuzz.ratio(a[-1], b[-1]) < 96:
        return False
    if a[0] == b[0]:
        return True
    return min(len(a[0]), len(b[0])) == 1 and a[0][0] == b[0][0]


def _display_name(value: str) -> str:
    if ',' in value:
        last, first = value.split(',', 1)
        if len(_person_tokens(value)) >= 2:
            return _clean(first + ' ' + last)
    return _clean(value).rstrip('.')


def infer_metadata(segments: Iterable[EvidenceSegment], metadata: dict, form_id: str = '') -> dict:
    """Fill absent caption context; never silently overwrite a supplied identity."""
    result = dict(metadata)
    text = '\n'.join(s.text for s in segments)
    if not result.get('plaintiff'):
        m = re.search(r'\b(?:The\s+)?Plaintiff\s*[:,]\s*([A-Z][A-Za-z .\'-]+?)(?:,|\s+(?:resides|is|has)\b|\n|:)', text)
        if m:
            result['plaintiff'] = _clean(m.group(1))
    if not result.get('defendant'):
        m = re.search(r'\b(?:The\s+)?Defendant\s*[:,]\s*([A-Z][A-Za-z .\'-]+?)(?:,|\s+(?:resides|is|has)\b|\n|:)', text)
        if m:
            result['defendant'] = _clean(m.group(1))
    if form_id == '202':
        result['responding_party_role'] = 'plaintiff'
    # Form 207 needs an express order or the matter's approved role. Do not
    # equate the family-court respondent with the discovery responding party.
    if form_id == '207':
        order = re.search(r'\b(?:ORDERED|ORDER)\b[\s\S]{0,180}?\b(Plaintiff|Defendant)\b[\s\S]{0,100}?\b(?:answer|respond to)\b[\s\S]{0,80}?\binterrogator', text, re.I)
        if order:
            ordered_role = order.group(1).lower()
            approved_role = result.get('responding_party_role', '')
            if (approved_role and approved_role != ordered_role) or result.get('_responding_party_conflict'):
                result['responding_party_role'] = ''
                result['_responding_party_conflict'] = 'The matter responding-party role conflicts with the court order. Confirm the correct party before drafting.'
            else:
                result['responding_party_role'] = ordered_role
    return result


def case_context(metadata: dict) -> CaseContext:
    plaintiff, defendant = _clean(metadata.get('plaintiff', '')), _clean(metadata.get('defendant', ''))
    role = str(metadata.get('responding_party_role', '')).strip().lower()
    respondent = plaintiff if role == 'plaintiff' else defendant if role == 'defendant' else ''
    return CaseContext(plaintiff, defendant, role, respondent, str(metadata.get('interrogating_party', '')), str(metadata.get('response_date', '')))


def requirement_for(item: FormItem) -> Requirement:
    wording = ' '.join(p for p in (item.prompt, item.text) if p).strip()
    attrs = _ITEM_REQUIREMENTS.get(item.item_id)
    if attrs is None:
        raise ValueError(f'No extraction targets defined for selected field {item.item_id}')
    condition, expected = _CONDITIONS.get(item.item_id, ('', 'true'))
    lower = wording.lower()
    period = 'current' if any(w in lower for w in ('current', 'present', 'presently')) else 'historical' if any(w in lower for w in ('prior', 'preceding', 'last three years', 'date of the incident')) else 'unspecified'
    typ = 'boolean' if lower.startswith(('do ', 'did ', 'are ', 'is ', 'have ')) else 'structured'
    return Requirement(item.item_id, wording, 'responding_party', attrs, period, typ, condition, expected)


def _classification(filename: str, text: str) -> str:
    lower = text.lower()
    # Content describes this record. A complaint and police report can share
    # one PDF: the filename alone must not determine the truth of every page.
    if any(x in lower for x in ('uniform crash report', 'discharge summary', 'medical record', 'visit log', 'payroll')):
        return 'THIRD_PARTY_RECORD'
    if 'declaration under oath' in lower or 'sworn' in filename.lower():
        return 'SWORN_DECLARATION'
    if any(x in filename.lower() for x in ('court_order', 'court order', 'judgment')):
        return 'JUDICIAL_FINDING'
    if any(x in filename.lower() for x in ('complaint', 'allegation', 'demand letter')):
        return 'ALLEGATION'
    return 'THIRD_PARTY_RECORD' if any(x in filename.lower() for x in ('medical', 'payroll', 'record', 'invoice', 'hospital')) else 'REPORTED_FACT'


def _label(text: str) -> tuple[str, str] | None:
    for attr, pattern in _LABEL_PATTERNS:
        match = pattern.match(text.strip())
        if match:
            return attr, match.group(1).strip(' _:\t')
    return None


def _value_key(attribute: str, value: str) -> str:
    if 'date' in attribute or attribute == 'date_of_birth':
        normalized = _date(value)
        if normalized:
            return normalized
    if attribute == 'full_name':
        return ' '.join(_person_tokens(value))
    lower = value.lower()
    if 'address' in attribute:
        for a, b in (('connecticut', 'ct'), ('avenue', 'ave'), ('street', 'st'), ('road', 'rd'), ('apartment', 'apt'), ('suite', 'ste'), ('drive', 'dr')):
            lower = re.sub(r'\b' + a + r'\b', b, lower)
    return re.sub(r'[^a-z0-9]+', '', lower)


def _identity_subject(name, context):
    matches = [n for n in (context.plaintiff, context.defendant) if _same_person(name, n)]
    return matches[0] if len(matches) == 1 else 'ambiguous' if len(matches) > 1 else _display_name(name)


def _subject(text: str, context: CaseContext) -> str:
    inline = _inline_fields(text)
    if len(inline) > 1:
        name = next((v for a,v in inline if a == 'full_name'), '')
        if name:
            return _identity_subject(name, context)
    label = _label(text)
    if label and label[0] == 'full_name' and label[1]:
        name = label[1]
        return _identity_subject(name, context)
    found = []
    for name in (context.plaintiff, context.defendant):
        if name and name.casefold() in text.casefold():
            found.append(name)
    if len(found) == 1:
        return found[0]
    if len(found) > 1:
        return 'ambiguous'
    if re.search(r'\bresponding party\b|\brespondent\b', text, re.I):
        return context.responding_party
    if re.search(r'\bplaintiff\b', text, re.I) and not re.search(r'\bdefendant\b', text, re.I):
        return context.plaintiff
    if re.search(r'\bdefendant\b', text, re.I) and not re.search(r'\bplaintiff\b', text, re.I):
        return context.defendant
    # Evidence initials and surname variants; a bare surname never establishes
    # identity if another named party could share it.
    for match in re.finditer(r"(?:[A-Z][A-Za-z'-]+,\s*(?:[A-Z][A-Za-z'-]*\.?\s*){1,3}|(?:[A-Z][a-z]+|[A-Z]\.)(?:\s*[A-Z]\.)?\s+[A-Z][A-Za-z'-]+)", text):
        candidates = [n for n in (context.plaintiff, context.defendant) if _same_person(match.group(), n)]
        if len(candidates) == 1:
            return candidates[0]
    return 'unknown'


def _period(text: str) -> str:
    if re.search(r'\b(?:current|currently|present|presently|as of)\b', text, re.I):
        return 'current'
    m = re.search(r'\b(?:19|20)\d{2}\b', text)
    return m.group() if m else 'unspecified'


def extract_facts(segments: Iterable[EvidenceSegment], metadata: dict, documents: Iterable[dict],
                  items: Iterable[FormItem] | None = None, diagnostics: list | None = None) -> list[Fact]:
    segments = list(segments)
    selected = list(items) if items is not None else []
    form_id = selected[0].item_id.split('-')[0] if selected else str(metadata.get('form_id', ''))
    metadata = infer_metadata(segments, metadata, form_id)
    context = case_context(metadata)
    docmap = {str(d.get('source_id', '')): d for d in documents}
    targets = {a for item in selected for a in requirement_for(item).attributes} if selected else {a for attrs in _ITEM_REQUIREMENTS.values() for a in attrs}
    auxiliary = {'owns_subject_vehicle', 'treatment_date', 'treatment_provider', 'treatment_location', 'treatment_provider_address',
                 'self_employed', 'unable_to_work_disability', 'owns_rental_property', 'trust_party', 'hourly_rate',
                 'current_weekly_hours', 'uploaded_medical_report', 'prehospital_provider', 'prehospital_details', 'permanency_assessment', 'existing_support_order', 'recovery_status'} | {'answer_' + item.item_id for item in selected}
    facts: list[Fact] = []
    seen = set()
    pages: dict[tuple, list[EvidenceSegment]] = defaultdict(list)
    for seg in segments:
        pages[(seg.source_id, seg.page)].append(seg)

    def add(attr: str, value: str, source: list[EvidenceSegment], subject: str, attribution: EvidenceSegment | None = None,
            unit: str = '', period: str = 'unspecified', group: str = '', original: str = '') -> None:
        value = _clean(value).rstrip(';')
        if not value or attr not in targets | auxiliary:
            return
        if attr == 'current_weekly_hours' and not re.fullmatch(r'\d+(?:\.\d+)?', value):
            return
        quote = '\n'.join(s.text for s in source)
        first = source[0]
        classification = _classification(first.filename, quote)
        key = (attr, subject.casefold(), value.casefold(), first.segment_id, group)
        if key in seen:
            return
        seen.add(key)
        normalized = _value_key(attr, value)
        facts.append(Fact(
            'F-' + hashlib.sha256(repr(key).encode()).hexdigest()[:16], subject, attr, value, unit, period,
            first.source_id, first.filename, str(docmap.get(first.source_id, {}).get('sha256', '')),
            first.page, quote, first.segment_id, classification, 'VERIFIED_SOURCE',
            original or value, normalized, first.extraction_method, any(s.ocr_sourced for s in source),
            .75 if classification == 'ALLEGATION' else .85 if classification == 'REPORTED_FACT' else 1.0,
            attribution.text if attribution else '', attribution.segment_id if attribution else '',
            tuple(s.segment_id for s in source), group,
        ))

    for (source_id, page_no), lines in pages.items():
        text = '\n'.join(s.text for s in lines)
        patient_headers = [s for s in lines if re.match(r'^(?:Patient(?: Name)?|Re)(?:\s+|:\s*)', s.text, re.I)]
        patient_subjects = {sub for s in patient_headers if (sub := _subject(s.text, context)) not in {'unknown', 'ambiguous', ''}}
        page_subject = next(iter(patient_subjects)) if len(patient_subjects) == 1 else 'unknown'
        attribution = next((s for s in patient_headers if _subject(s.text, context) == page_subject), None)
        current = page_subject
        table_headers: list[str] = []
        grouped = []
        is_complaint = any(s.text.strip() == 'COMPLAINT' for s in lines)
        i = 0
        while i < len(lines):
            seg = lines[i]
            if is_complaint and re.match(r'^\d+\.\s', seg.text):
                j = i + 1
                while j < len(lines) and not re.match(r'^\d+\.\s|^[A-Z][A-Z ,\-]{8,}$', lines[j].text):
                    j += 1
                grouped.append(lines[i:j])
                i = j
            else:
                grouped.append([seg])
                i += 1
        for group_lines in grouped:
            seg = group_lines[0]
            line = ' '.join(s.text for s in group_lines)
            if re.match(r'^VEHICLE\s+\d+\b', line, re.I):
                current, attribution = 'unknown', None
            detected = _subject(line, context)
            parsed = _label(line)
            if detected not in {'unknown', 'ambiguous', ''}:
                current = detected
                attribution = seg
            subject = detected if detected != 'unknown' else current
            if subject == 'ambiguous':
                subject = 'unknown'
            if seg.cells and len(seg.cells) > 1:
                headers = [_LABEL_LOOKUP.get(re.sub(r'[^a-z0-9]+', ' ', c.lower()).strip(), '') for c in seg.cells]
                if sum(bool(h) for h in headers) >= 2:
                    table_headers = headers
                    continue
                if table_headers and len(table_headers) == len(seg.cells):
                    values = dict(zip(table_headers, seg.cells))
                    if values.get('full_name'):
                        name = values['full_name']
                        subject = _identity_subject(name, context)
                        current, attribution = subject, seg
                    for attr, value in zip(table_headers, seg.cells):
                        if attr:
                            add(attr, _display_name(value) if attr == 'full_name' else value, group_lines, subject, attribution)
                elif _label(seg.cells[0]):
                    parsed = (_label(seg.cells[0])[0], ' '.join(seg.cells[1:]))
                    if seg.ocr_sourced:
                        anchors = [s for s in lines if not s.ocr_sourced and _label(s.text) == (parsed[0], '') and s.bbox and seg.bbox and abs(s.bbox[1] - seg.bbox[1]) <= 24]
                        if anchors:
                            a, b = sorted((lines.index(anchors[0]), lines.index(seg)))
                            group_lines = lines[a:b + 1]
            inline = _inline_fields(line)
            if len(inline) > 1:
                name = next((v for a,v in inline if a == 'full_name'), '')
                if name:
                    subject = _identity_subject(name, context)
                    current, attribution = subject, seg
                for attr, value in inline:
                    if attr == 'date_of_birth':
                        m = _DATE.search(value)
                        if m and _date(value):
                            add(attr, m.group(), group_lines, subject, attribution, unit='date')
                    else:
                        add(attr, _display_name(value) if attr == 'full_name' else value, group_lines, subject, attribution)
                parsed = None
            if parsed:
                attr, value = parsed
                used = group_lines
                if not value:
                    ordinal = lines.index(seg)
                    if ordinal + 1 < len(lines) and not _label(lines[ordinal + 1].text) and not re.match(r'^VEHICLE\b', lines[ordinal + 1].text, re.I):
                        value = lines[ordinal + 1].text
                        used = [seg, lines[ordinal + 1]]
                if value and 'address' in attr and not re.search(r'\b\d{5}(?:-\d{4})?\b', value):
                    ordinal = lines.index(used[-1])
                    for following in lines[ordinal + 1:ordinal + 3]:
                        if _label(following.text):
                            break
                        if re.search(r'\b[A-Z]{2}\s+\d{5}\b|\bConnecticut\s+\d{5}\b|^(?:Apt|Apartment|Suite|Unit)\b', following.text):
                            value += ' ' + following.text
                            used = [*used, following]
                        else:
                            break
                if value:
                    if attr == 'full_name':
                        subject = _identity_subject(value, context)
                        current, attribution = subject, seg
                        add(attr, _display_name(value), used, subject, attribution, original=value)
                    elif attr == 'date_of_birth':
                        match = _DATE.search(value)
                        if match and _date(value):
                            add(attr, match.group(), used, subject, attribution, unit='date')
                    else:
                        add(attr, value, used, subject, attribution)
                        if attr in {'vehicle_owner', 'home_address', 'employer_name', 'employer_address'}:
                            if attr == 'vehicle_owner' and re.search(r'\bsame as (?:the )?operator\b', value, re.I):
                                add('owns_subject_vehicle', 'true', used, subject, attribution, unit='boolean')
                            if attr == 'employer_name':
                                add('incident_employer_name', value, used, subject, attribution)
                            if attr == 'employer_address':
                                add('business_address', value, used, subject, attribution)
                                add('incident_employer_address', value, used, subject, attribution)
            # A prior numbered answer is a question-driven source even when its
            # subject matter has no common header alias.
            for item in selected:
                label = f'{item.number}' + (f'({item.label})' if item.label else '')
                direct = re.match(r'^(?:Answer|Response)\s+(?:to\s+)?(?:Interrogatory\s+)?' + re.escape(label) + r'\s*[:=]\s*(.+)', line, re.I)
                if direct:
                    add('answer_' + item.item_id, direct.group(1), group_lines, subject, attribution)
            explicit = re.search(r'\bfact\s*:\s*subject\s*=\s*([^;]+);\s*attribute\s*=\s*([a-z0-9_]+);\s*value\s*=\s*([^;]+)(?:;\s*unit\s*=\s*([^;]+))?(?:;\s*period\s*=\s*([^;.]+))?', line, re.I)
            if explicit:
                add(explicit[2].lower(), explicit[3], group_lines, explicit[1].strip(), seg, explicit[4] or '', explicit[5] or _period(line))
            if subject == context.responding_party:
                m = re.search(r'\bresides at\s+(.+?)(?:\.\s|\.$|$)', line, re.I)
                if m:
                    add('home_address', m[1], group_lines, subject, attribution, unit='address')
                m = re.search(r'\b(?:full name|legal name)\s+is\s+(.+?)(?:\.$|$)', line, re.I)
                if m:
                    add('full_name', m[1], group_lines, subject, attribution)
                m = re.search(r'\b(?:date of birth\s*(?:is|:)|born (?:on )?)\s*(' + _DATE.pattern + ')', line, re.I)
                if m:
                    add('date_of_birth', m[1], group_lines, subject, attribution, unit='date')
                m = re.search(r'\b(?:sustained|diagnosed with|suffered)\s+(?:an?\s+)?(.+?)(?:\s+as a result of the incident|\.$|$)', line, re.I)
                if m:
                    for value in re.split(r';\s*(?:and\s+)?', m[1]):
                        add('incident_injury', value.rstrip('.'), group_lines, subject, attribution)
                if re.search(r'\b(?:his|her|their) own\s+\d{4}\s+\w+', line, re.I):
                    add('owns_subject_vehicle', 'true', group_lines, subject, attribution, unit='boolean')
                if re.search(r'\b(?:has not|not fully|not yet) recovered\b', line, re.I):
                    add('recovery_status', 'Not fully recovered', group_lines, subject, attribution)
                m = re.search(r'\b(?:continues? to (?:suffer|experience)|presently suffering)\s+(.+?)(?:,?\s+and (?:has|have) not recovered|\.$|$)', line, re.I)
                if m:
                    add('present_complaints', m[1], group_lines, subject, attribution, period='current')
                money = re.search(r'\$\s*\d[\d,]*(?:\.\d{2})?', line)
                if money and re.search(r'\b(?:income|earnings|wage|salary)\b', line, re.I):
                    basis = 'gross' if re.search(r'\bgross\b', line, re.I) else 'net' if re.search(r'\bnet\b', line, re.I) else ''
                    if basis == 'gross' and re.search(r'per week|weekly|/week', line, re.I):
                        period = _period(line)
                        attr = 'current_gross_weekly_income' if period == 'current' else 'historical_gross_weekly_income' if re.search(r'average|preceding year', line, re.I) else 'dated_gross_weekly_income'
                        add(attr, money.group().replace(' ', ''), group_lines, subject, attribution, 'USD/week', period)
                m = re.search(r'\b(?:works?|working)\s+(\d+(?:\.\d+)?)\s*hours?\s*(?:per week|weekly)', line, re.I)
                if m:
                    add('current_weekly_hours', m[1], group_lines, subject, attribution, 'hours/week', _period(line))
                for attr, positive, negative in (
                    ('self_employed', r'\b(?:is|am) self-employed\b', r'\b(?:is|am) not self-employed\b'),
                    ('owns_rental_property', r'\bowns? (?:an? |any )?rental propert', r'\bdoes not own (?:an? |any )?rental propert|\bowns no rental propert'),
                    ('unable_to_work_disability', r'\b(?:cannot|unable to) work (?:because|due to) (?:a )?disability\b', r'\bcan work\b'),
                    ('trust_party', r'\b(?:is|am) (?:a )?(?:beneficiary|settlor) of (?:a )?trust\b', r'\b(?:is|am) not (?:a )?(?:beneficiary|settlor) of (?:a )?trust\b'),
                    ('current_treatment', r'\b(?:is|am) (?:currently|presently) (?:under|receiving) (?:the )?(?:care|treatment)\b', r'\b(?:is|am) not (?:currently|presently) (?:under|receiving) (?:the )?(?:care|treatment)\b'),
                    ('present_disability', r'\b(?:has|have) (?:a )?present disability\b', r'\b(?:has|have) no present disability\b'),
                    ('permanent_disability', r'\b(?:has|have) (?:a )?permanent disability\b', r'\b(?:has|have) no permanent disability\b'),
                ):
                    if re.search(negative, line, re.I):
                        add(attr, 'false', group_lines, subject, attribution, 'boolean', _period(line))
                    elif re.search(positive, line, re.I):
                        add(attr, 'true', group_lines, subject, attribution, 'boolean', _period(line))
            # Witnesses are facts about the incident, not the witness's DOB or
            # address becoming a plaintiff identity fact.
            witness = re.search(r'\bWitness\s*:\s*(.+)', line, re.I)
            if witness:
                add('incident_witness', witness[1].rstrip('.'), group_lines, context.responding_party, seg)
        if page_subject == context.responding_party:
            _medical_facts(lines, context.responding_party, attribution, add)
            _employment_facts(lines, context.responding_party, attribution, add)
    if diagnostics is not None:
        for seg in segments:
            found = [f for f in facts if seg.segment_id in f.source_segment_ids]
            diagnostics.append({'source_id': seg.source_id, 'document': seg.filename, 'page': seg.page,
                'segment_id': seg.segment_id, 'text': seg.text, 'method': seg.extraction_method, 'ocr_sourced': seg.ocr_sourced,
                'facts': [f.to_dict() for f in found], 'decision': 'EXTRACTED_FACTS' if found else 'NO_TARGET_FACT',
                'reason': 'Matched a selected question target or supporting context' if found else 'No explicit selected-question fact established in this block'})
    return facts


def _medical_facts(lines, subject, attribution, add):
    text = '\n'.join(s.text for s in lines)
    if not re.search(r'\b(?:hospital|orthopaedics?|orthopedics?|neurology|rehabilitation|medical|clinic|physical therapy|prehospital)\b', text, re.I):
        return
    facility = next((s for s in lines[:7] if re.search(r'\b(?:HOSPITAL|ORTHOPAEDICS|ORTHOPEDICS|NEUROLOGY|REHABILITATION|CLINIC|PHYSICAL THERAPY)\b', s.text, re.I) and not re.match(r'^(?:Consults|Destination|Patient|Follow)', s.text, re.I)), None)
    address = next((s for s in lines[:7] if re.match(r'^\d+\s+.+\b[A-Z]{2}\s+\d{5}', s.text)), None)
    provider = next((s for s in lines if re.match(r'^(?:Attending|Physician|Provider|Therapist)(?:\s+|:\s*)', s.text, re.I)), None)
    provider_name = re.sub(r'^(?:Attending|Physician|Provider|Therapist)\s*:?\s*', '', provider.text, flags=re.I) if provider else ''
    if re.search(r'PREHOSPITAL CARE REPORT|EMS RUN SHEET', text, re.I):
        add('prehospital_provider', lines[0].text, lines, subject, attribution)
        interventions = next((s for s in lines if re.match(r'^(?:Interventions|Treatment)(?:\s+|:)', s.text, re.I)), None)
        if interventions:
            add('prehospital_details', interventions.text, [interventions], subject, attribution)

    if provider_name:
        value = provider_name + (', ' + facility.text if facility else '')
        source = lines[:lines.index(provider) + 1]
        add('treating_provider', value, source, subject, attribution, group=f'{lines[0].source_id}:p{lines[0].page}')
        if address:
            add('provider_address', provider_name + ': ' + address.text, source, subject, attribution)
    # A numbered diagnosis list belongs to its diagnosed patient, not to a
    # sentence that happens to contain the patient's full name.
    start = next((i for i,s in enumerate(lines) if re.fullmatch(r'(?:DISCHARGE )?DIAGNOS(?:ES|IS)\s*:?', s.text, re.I)), None)
    if start is not None:
        end = next((i for i in range(start + 1,len(lines)) if re.fullmatch(r'[A-Z][A-Z ]{5,}', lines[i].text)), len(lines))
        source = lines[start:end]
        body = ' '.join(s.text for s in source[1:])
        values = re.split(r'(?:^|\s)\d+[.)]\s+', body)
        for value in values:
            if value.strip():
                add('incident_injury', value.strip().rstrip('.'), source, subject, attribution)
    events = []
    for i, seg in enumerate(lines):
        if re.match(r'^(?:Admission|Admitted|Discharge|Visit Date|Date of Visit|Date of Service|Treatment Date|OPERATIVE NOTE|POST.OP VISIT|FOLLOW.UP)\b', seg.text, re.I) or re.match(r'^\d{1,2}/\d{1,2}/\d{2,4}\s+\S', seg.text):
            date = _date(seg.text)
            if not date:
                continue
            group = seg.segment_id
            events.append((date, seg))
            add('treatment_date', _DATE.search(seg.text).group(), [seg], subject, attribution, 'date', group=group)
            if provider:
                add('treatment_provider', provider_name, [provider], subject, attribution, group=group)
            if facility:
                add('treatment_location', facility.text, [facility], subject, attribution, group=group)
            if address:
                add('treatment_provider_address', address.text, [address], subject, attribution, group=group)
            if re.match(r'^Admission|^Admitted', seg.text, re.I) and facility and 'hospital' in facility.text.lower():
                add('hospital_name', facility.text, [facility], subject, attribution)
                add('hospital_admission', seg.text, [seg], subject, attribution)
                if address:
                    add('hospital_location', address.text, [address], subject, attribution)
            if re.match(r'^Discharge(?:\s+|:)', seg.text, re.I) and facility and 'hospital' in facility.text.lower():
                add('hospital_discharge', seg.text, [seg], subject, attribution)
    if events and provider:
        dates = ', '.join(dict.fromkeys(_DATE.search(s.text).group() for _,s in events))
        description = (facility.text + ': ' if facility else '') + provider_name + '; documented dates: ' + dates
        if address:
            description += '; address: ' + address.text
        add('uploaded_medical_report', description, lines, subject, attribution)
    if events and provider and re.search(r'\b(?:Continuing|Not discharged|Continue medication|Return\s+\d+\s+months|Begin formal PT)\b', text, re.I):
        selected = [s for s in lines if re.search(r'Continuing|Not discharged|Continue medication|Return\s+\d+\s+months|Begin formal PT', s.text, re.I)]
        add('current_treatment', 'true', selected, subject, attribution, 'boolean', 'current')
        add('current_treatment_provider', provider_name + (', ' + facility.text if facility else ''), lines[:lines.index(provider) + 1], subject, attribution, period='current')
        if address:
            add('current_provider_address', provider_name + ': ' + address.text, [address], subject, attribution, period='current')
    for i,seg in enumerate(lines):
        source = lines[i:min(i+2,len(lines))]
        joined = ' '.join(s.text for s in source)
        if re.search(r'permanency to be assessed|permanen(?:t|cy).*(?:undetermined|not determined)', joined, re.I):
            statement = re.search(r'permanency to be assessed[^.]*|permanen(?:t|cy)[^.]*?(?:undetermined|not determined)[^.]*', joined, re.I)
            add('permanency_assessment', statement.group() if statement else joined, source, subject, attribution)


def _employment_facts(lines, subject, attribution, add):
    text = ' '.join(s.text for s in lines)
    if not re.search(r'\b(?:has been employed|employment verification|human resources|employer letter)\b', text, re.I):
        return
    header = lines[0]
    address = next((s for s in lines[1:5] if re.match(r'^\d+\s+.+\b[A-Z]{2}\s+\d{5}', s.text)), None)
    source = lines
    if address:
        for attr in ('incident_employer_name','employer_name'):
            add(attr, header.text, lines[:lines.index(address)+1], subject, attribution)
        for attr in ('incident_employer_address','employer_address','business_address'):
            add(attr, address.text, [address], subject, attribution)
    m = re.search(r'employed as (?:an? )?(.+?)\s+(?:at|since|for)\b', text, re.I)
    if m:
        add('incident_occupation', m[1], source, subject, attribution)
    hours = re.search(r'(\d+(?:\.\d+)?)\s+hours per week', text, re.I)
    if re.search(r'has been employed.+?since\s+(?:[A-Za-z]+\s+)?(?:19|20)\d{2}', text, re.I) and address:
        add('prior_employer', header.text + ': ' + address.text, source, subject, attribution)
    if hours:
        add('current_weekly_hours', hours[1], source, subject, attribution, 'hours/week')
    wage = re.search(r'(\$\d[\d,]*(?:\.\d{2})?)\s+per hour', text, re.I)
    if wage:
        add('hourly_rate', wage[1], source, subject, attribution, 'USD/hour')
        add('pay_basis', 'Hourly', source, subject, attribution)
    m = re.search(r'(?:unable to work|out of work) since\s+(' + _DATE.pattern + ')', text, re.I)
    letter_date = next((s.text for s in lines[:6] if _date(s.text) and not re.match(r'^\d+\s', s.text)), '')
    if m:
        value = 'Unable to work since ' + m[1]
        if re.search(r'has not returned', text, re.I):
            value += '; not returned as of ' + (letter_date or 'the employer letter')
        add('lost_work_dates', value, source, subject, attribution)
    if re.search(r'has not returned', text, re.I):
        add('work_resumption_date', 'Has not returned as of ' + (letter_date or 'the employer letter'), source, subject, attribution)


def _source_valid(fact: Fact, segments: list[EvidenceSegment], hashes: dict[str, str]) -> bool:
    if not hashes.get(fact.source_id) or fact.document_sha256 != hashes[fact.source_id]:
        return False
    page = [s for s in segments if s.source_id == fact.source_id and s.page == fact.page]
    quote = _clean(fact.quote)
    if not quote or quote not in _clean('\n'.join(s.text for s in page)):
        return False
    ids = {s.segment_id for s in page}
    if fact.source_segment_ids and not set(fact.source_segment_ids) <= ids:
        return False
    if fact.attribution_segment_id and not any(s.segment_id == fact.attribution_segment_id and s.text == fact.attribution_quote for s in page):
        return False
    return True


def _citation(fact: Fact) -> dict:
    value = fact.to_dict()
    value['matched_terms'] = [fact.attribute.replace('_', ' ')]
    value['citation_validated'] = True
    return value


def _unique(facts: list[Fact]) -> list[Fact]:
    seen = set()
    result = []
    for f in facts:
        key = (f.source_id, f.page, f.quote, f.attribute, f.value)
        if key not in seen:
            seen.add(key)
            result.append(f)
    return result


def _values(facts: list[Fact], attr: str) -> list[str]:
    grouped: dict[str, list[Fact]] = defaultdict(list)
    for fact in facts:
        if fact.attribute == attr:
            grouped[_value_key(attr, fact.value)].append(fact)
    return [max(group, key=lambda f: len(f.value)).value for group in grouped.values()]


def _injuries(facts: list[Fact]) -> list[str]:
    grouped = defaultdict(list)
    for f in facts:
        if f.attribute != 'incident_injury':
            continue
        lower = f.value.lower()
        category = next((c for c in ('concussion', 'fracture', 'strain', 'lacerat', 'contusion', 'sprain', 'disc bulg') if c in lower), '')
        sites = tuple(x for x in ('clavicle','lumbar','scalp','knee','cervical','neck','shoulder','ankle','wrist','left','right','bilateral') if x in lower)
        key = (category, sites) if category else ('literal', _value_key('', lower))
        grouped[key].append(f)
    # Prefer the diagnosis list's clinical wording; retain every source citation.
    return [max(group, key=lambda f: ('DIAGNOS' in f.quote.upper(), len(f.value))).value for group in grouped.values()]


def _compose(requirement: Requirement, facts: list[Fact], context: CaseContext) -> str:
    q = requirement.question_id
    if q == '202-3' and any(f.attribute == 'prehospital_provider' for f in facts):
        provider = _values(facts, 'prehospital_provider')[0]
        details = '; '.join(_values(facts, 'prehospital_details'))
        date = '; '.join(_values(facts, 'first_treatment_date'))
        hospital = '; '.join(_values(facts, 'first_treatment_location'))
        attending = '; '.join(_values(facts, 'first_treatment_provider'))
        return f'Prehospital care is documented by {provider}. {details}. The run sheet does not state a service date. The earliest dated hospital care in the uploaded records is {date} at {hospital}, with {attending}.'
    if q == '202-16' and any(f.attribute == 'uploaded_medical_report' for f in facts):
        return 'Uploaded medical records: ' + '; '.join(_values(facts, 'uploaded_medical_report')) + '. Receipt by the responding party or counsel, completeness of reports received, and anticipated trial witnesses are not established.'
    if q == '202-1-a':
        names = [f.value for f in facts if f.attribute == 'full_name']
        best = max(names, key=lambda n: (sum(len(t) > 1 for t in _person_tokens(n)), len(n))) if names else ''
        aliases = _values(facts, 'other_names')
        return (f'Full name: {best}.' if best else '') + (' Other names used: ' + '; '.join(aliases) + '.' if aliases else '')
    if q == '202-2':
        return '; '.join(_injuries(facts)) + '.'
    if q == '202-7' and any(f.attribute == 'recovery_status' for f in facts):
        return '; '.join(_values(facts, 'recovery_status')) + '. No full recovery date is stated.'
    if q == '202-23-c' and not any(f.attribute == 'historical_gross_weekly_income' for f in facts):
        rate, hours = _values(facts, 'hourly_rate'), _values(facts, 'current_weekly_hours')
        return 'The employer letter records ' + (rate[0] + ' per hour' if rate else '') + (' and ' + hours[0] + ' hours per week' if hours else '') + '. The average weekly earnings for the year preceding the incident are not stated.'
    if q == '207-3-c':
        return f"The responding party's current gross weekly employment income is {_values(facts, 'current_gross_weekly_income')[0]}."
    if q == '207-1-a':
        return f"The responding party's present residence is {_values(facts, 'home_address')[0]}."
    if q == '207-3-d':
        return f"The responding party usually works {_values(facts, 'current_weekly_hours')[0]} hours per week."
    clauses = []
    for attribute in dict.fromkeys([*requirement.attributes, *[f.attribute for f in facts if f.attribute == 'permanency_assessment']]):
        values = _values(facts, attribute)
        if values:
            if attribute == 'current_treatment' and set(values) <= {'true', 'false'}:
                values = ['Yes' if v == 'true' else 'No' for v in values]
            clauses.append(_ATTRIBUTE_LABELS.get(attribute, attribute.replace('_', ' ')).capitalize() + ': ' + '; '.join(values))
    if q in {'202-3', '202-6'}:
        clauses.insert(0, 'Earliest dated treatment in the uploaded records' if q == '202-3' else 'Latest dated treatment in the uploaded records')
    return '. '.join(clauses) + ('.' if clauses else '')


def build_response(item: FormItem, segments: list[EvidenceSegment], facts: list[Fact], metadata: dict,
                   documents: list[dict]) -> dict:
    from dataclasses import replace
    requirement = requirement_for(item)
    metadata = infer_metadata(segments, metadata, item.item_id.split('-')[0])
    context = case_context(metadata)
    hashes = {str(d.get('source_id','')): str(d.get('sha256','')) for d in documents}
    candidates = [c.to_dict() for c in rank_evidence(item, segments)]
    for c in candidates:
        c['document_sha256'] = hashes.get(c['source_id'], '')
        c['evidence_classification'] = _classification(c['filename'], c['quote'])
    base = dict(engine_status='EMPTY', status='EMPTY', evidence_outcome='NO_RESPONSIVE_EVIDENCE', reason_code='NOT_IN_EVIDENCE',
                answer='', generated_answer='', supporting_citations=[], evidence=candidates, candidate_passages=candidates,
                missing_information=[_ATTRIBUTE_LABELS.get(a,a.replace('_',' ')) for a in requirement.attributes],
                required_follow_up='Obtain responsive evidence or client confirmation.', conflicts=[], requirement=requirement.to_dict(),
                edit_history=[], requires_revalidation=False, approval=None)
    if not context.responding_party:
        base.update(engine_status='REQUIRES_CLIENT', status='REQUIRES_CLIENT', evidence_outcome='IDENTITY_UNRESOLVED', reason_code='IDENTITY_UNRESOLVED', required_follow_up=metadata.get('_responding_party_conflict', 'Confirm the discovery responding party from the caption and order.'))
        return base
    applicable = [f for f in facts if f.subject.casefold() == context.responding_party.casefold() and _source_valid(f, segments, hashes)]
    condition_note = ''
    if requirement.conditional_attribute:
        conditions = [f for f in applicable if f.attribute == requirement.conditional_attribute]
        values = {f.value.lower() for f in conditions}
        if len(values) > 1:
            base.update(engine_status='POTENTIAL_CONFLICT', status='POTENTIAL_CONFLICT', evidence_outcome='EVIDENCE_CONFLICT', reason_code='CONFLICTING_SOURCES',
                conflicts=[{'attribute': requirement.conditional_attribute, 'description': 'Conflicting applicability evidence.', 'facts': [f.to_dict() for f in conditions]}],
                supporting_citations=[_citation(f) for f in conditions], evidence=[_citation(f) for f in conditions],
                required_follow_up='Resolve conflicting applicability evidence.')
            return base
        if values == {'false'}:
            text = 'Not applicable: the cited record expressly states ' + requirement.conditional_attribute.replace('_',' ') + ' is false.'
            base.update(engine_status='DRAFT', status='DRAFT', evidence_outcome='SUPPORTED_NOT_APPLICABLE', reason_code='', answer=text, generated_answer=text,
                missing_information=[], supporting_citations=[_citation(f) for f in conditions], evidence=[_citation(f) for f in conditions])
            return base
        if not conditions:
            condition_note = 'Applicability is not established by the uploaded evidence.'
    q = item.item_id
    if q == '202-1-f':
        owner = [f for f in applicable if f.attribute == 'owns_subject_vehicle' and f.value == 'true']
        if owner:
            text = 'Not applicable: the plaintiff owned the vehicle, according to the cited records.'
            base.update(engine_status='DRAFT', status='DRAFT', evidence_outcome='SUPPORTED_NOT_APPLICABLE', reason_code='', answer=text, generated_answer=text,
                        supporting_citations=[_citation(f) for f in owner], evidence=[_citation(f) for f in owner], missing_information=[])
            return base
    matched = [f for f in applicable if f.attribute in requirement.attributes]
    # Choose a complete dated event, not the first/latest date anywhere on a page
    # (which could be DOB, imaging or a scheduled future appointment).
    if q in {'202-3','202-6'}:
        events = [f for f in applicable if f.attribute == 'treatment_date' and _date(f.value)]
        if events:
            chosen = min(events, key=lambda f: _date(f.value)) if q == '202-3' else max(events, key=lambda f: _date(f.value))
            event_facts = [f for f in applicable if f.record_group == chosen.record_group]
            mapping = {'treatment_date': 'first_treatment_date' if q == '202-3' else 'last_treatment_date',
                       'treatment_provider': 'first_treatment_provider' if q == '202-3' else 'last_treatment_provider',
                       'treatment_location': 'first_treatment_location' if q == '202-3' else 'last_treatment_location'}
            matched = [replace(f, attribute=mapping[f.attribute]) for f in event_facts if f.attribute in mapping and mapping[f.attribute] in requirement.attributes]
    if q == '202-3':
        matched += [f for f in applicable if f.attribute in {'prehospital_provider','prehospital_details'}]
    if q == '202-23-c' and not matched:
        matched = [f for f in applicable if f.attribute in {'hourly_rate','current_weekly_hours'}]
    if q == '202-16' and not matched:
        matched = [f for f in applicable if f.attribute == 'uploaded_medical_report']
    if q == '202-13' and not matched:
        matched = [f for f in applicable if f.attribute == 'permanency_assessment']
    if q in {'202-11', '202-12'} and not matched:
        matched = [f for f in applicable if f.attribute in {'present_complaints', 'lost_work_dates', 'work_resumption_date'}]
    if q.startswith('202-14-') and not matched:
        matched = [f for f in applicable if f.attribute == 'permanency_assessment']
    if q == '202-23-e' and not matched:
        matched = [f for f in applicable if f.attribute in {'hourly_rate', 'current_weekly_hours', 'lost_work_dates'}]
    if q == '207-3-c':
        matched = [f for f in matched if f.period in {'current','unspecified'}]
    # Full names may have initials or additional middle names; they are not
    # conflicting DOBs. Initial/name variants were identity-checked upstream.
    conflicts = []
    for attr in requirement.attributes:
        if attr in _MULTI_VALUE_ATTRIBUTES or attr == 'full_name':
            continue
        groups = defaultdict(list)
        for f in matched:
            if f.attribute == attr:
                groups[_value_key(attr, f.value)].append(f)
        if len(groups) > 1:
            conflicts.append({'attribute': attr, 'description': 'Conflicting values for ' + attr.replace('_',' ') + ': ' + ' / '.join(g[0].value for g in groups.values()),
                              'facts': [f.to_dict() for g in groups.values() for f in g]})
    if conflicts:
        cited = _unique([Fact(**f) for c in conflicts for f in c['facts']])
        base.update(engine_status='POTENTIAL_CONFLICT', status='POTENTIAL_CONFLICT', evidence_outcome='EVIDENCE_CONFLICT', reason_code='CONFLICTING_SOURCES', conflicts=conflicts,
                    supporting_citations=[_citation(f) for f in cited], evidence=[_citation(f) for f in cited],
                    required_follow_up='Resolve all conflicting values before inserting or approving an answer.')
        return base
    direct = [f for f in applicable if f.attribute == 'answer_' + q]
    if direct:
        if len({_value_key('', f.value) for f in direct}) > 1:
            base.update(engine_status='POTENTIAL_CONFLICT',status='POTENTIAL_CONFLICT', evidence_outcome='EVIDENCE_CONFLICT', reason_code='CONFLICTING_SOURCES',
                        conflicts=[{'description':'Conflicting numbered prior answers.','facts':[f.to_dict() for f in direct]}],
                        supporting_citations=[_citation(f) for f in direct])
            return base
        matched = direct
    if not matched:
        uncertain = [f for f in facts if f.attribute in requirement.attributes and f.subject in {'unknown','ambiguous',''} and _source_valid(f,segments,hashes)]
        if uncertain:
            base.update(engine_status='REQUIRES_CLIENT',status='REQUIRES_CLIENT', evidence_outcome='AMBIGUOUS_ATTRIBUTION', reason_code='CLIENT_CONFIRMATION_REQUIRED',
                candidate_passages=[_citation(f) for f in uncertain],evidence=[_citation(f) for f in uncertain],
                required_follow_up='Responsive values were found, but their attribution to the responding party is ambiguous. Confirm the party before insertion.')
        elif condition_note:
            base['required_follow_up'] = condition_note
        return base
    missing = [a for a in requirement.attributes if a not in {f.attribute for f in matched}]
    if direct:
        missing = []
    if q == '202-7' and any(f.attribute == 'recovery_status' and 'not' in f.value.lower() for f in matched):
        missing = []
    # Providers are a repeating collection. Each provider's absent address is a
    # specific gap even if some other provider's address is available.
    if q in {'202-5','202-10'}:
        provider_attr = 'treating_provider' if q == '202-5' else 'current_treatment_provider'
        address_attr = 'provider_address' if q == '202-5' else 'current_provider_address'
        addresses = ' '.join(f.value.lower() for f in matched if f.attribute == address_attr)
        for f in matched:
            if f.attribute == provider_attr:
                provider_name = f.value.split(',')[0].lower()
                if provider_name not in addresses:
                    missing.append('address for ' + f.value)
    if q == '202-3' and any(f.attribute == 'prehospital_provider' for f in matched):
        missing.append('Explicit service date and location of prehospital treatment')
    if condition_note:
        missing.append(condition_note)
    if q == '202-11':
        text = ('The cited records document ongoing limitations: ' + '; '.join(_values(matched, 'present_complaints')) +
                '. They also document: ' + '; '.join(_values(matched, 'lost_work_dates')) +
                '. Confirm whether the plaintiff claims these limitations as a present disability.')
        missing.append('client confirmation of a present disability claim')
    elif q == '202-12':
        text = ('The cited records describe the current limitations as: ' + '; '.join(_values(matched, 'present_complaints')) +
                '. Work status: ' + '; '.join(_values(matched, 'lost_work_dates')) + '.')
        missing.append('client confirmation that these limitations are claimed as a disability')
    elif q.startswith('202-14-'):
        detail = {
            '202-14-a': 'disabled body part', '202-14-b': 'lost motion or activity',
            '202-14-c': 'percentage of loss of use', '202-14-d': 'permanency evaluator',
            '202-14-e': 'prognosis date',
        }[q]
        text = (f'No {detail} is stated in the cited evidence. The orthopaedic record states: ' +
                '; '.join(_values(matched, 'permanency_assessment')) + '.')
        missing.append('client and attorney confirmation after the permanency assessment')
    elif q == '202-23-e':
        text = ('The cited employer record provides a calculation basis of ' +
                '; '.join(_values(matched, 'hourly_rate')) + ' per hour and ' +
                '; '.join(_values(matched, 'current_weekly_hours')) + ' hours per week. Documented work absence: ' +
                '; '.join(_values(matched, 'lost_work_dates')) + '. The total claimed loss is not established.')
        missing.append('total lost-income amount and final calculation')
    else:
        text = direct[0].value if direct else _compose(requirement, matched, context)
    cited = _unique(matched)
    outcome = 'PARTIAL_DRAFT' if missing else 'SUPPORTED_DRAFT'
    base.update(engine_status='DRAFT', status='DRAFT', evidence_outcome=outcome, reason_code='', answer=text, generated_answer=text,
                supporting_citations=[_citation(f) for f in cited], evidence=[_citation(f) for f in cited],
                missing_information=[_ATTRIBUTE_LABELS.get(a,a.replace('_',' ')) for a in dict.fromkeys(missing)],
                required_follow_up='Obtain the specifically missing information.' if missing else 'Attorney review and approval required.')
    return base


def answer_fingerprint(answer: dict) -> str:
    ids = sorted(str(c.get('fact_id',c.get('segment_id',''))) for c in answer.get('supporting_citations', []))
    return hashlib.sha256((str(answer.get('answer','')) + '|' + '|'.join(ids)).encode()).hexdigest()
