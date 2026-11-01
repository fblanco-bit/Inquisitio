"""Immutable Connecticut Form 205 requests paired with Form 202."""

FORM_205_REQUESTS = (
    "All hospital records relating to treatment received as a result of the alleged incident, and to injuries, diseases or defects to which reference is made in the answers to Interrogatories #19, #20, #21 and #22, or written authorization, sufficient to comply with the provisions of the Health Insurance Portability and Accountability Act (HIPAA), to inspect and make copies of said hospital records. Information obtained pursuant to HIPAA shall not be used or disclosed for any purpose other than this litigation or proceeding.",
    "All reports and records of all doctors and all other care providers relating to treatment allegedly received as a result of the alleged incident, and to the injuries, diseases or defects referenced in the answers to Interrogatories #19, #20, #21 and #22, exclusive of records prepared or maintained by a licensed psychiatrist or psychologist, or sufficient written HIPAA authorization to inspect and copy those reports. Information obtained pursuant to HIPAA shall not be used or disclosed for any purpose other than this litigation or proceeding.",
    "If a claim for lost wages or lost earning capacity is made, copies of, or sufficient written authorization to inspect and copy, the wage and employment records of all employers of the Plaintiff for three years before the incident and all years after the incident through the date of production.",
    "If impaired earning capacity or lost wages is alleged, copies of, or sufficient written authorization to obtain copies of, the portions of all income tax returns relating to lost income filed by the Plaintiff for three years before the incident and all years after the incident through trial.",
    "All property damage bills claimed to have been incurred as a result of this incident.",
    "All medical bills claimed to have been incurred as a result of this incident, or sufficient written HIPAA authorization to inspect and copy those bills. Information obtained pursuant to HIPAA shall not be used or disclosed for any purpose other than this litigation or proceeding.",
    "All bills for each item of expense claimed in the answer to Interrogatory #17 and not already provided in response to Requests #5 and #6.",
    "Copies of all documentation of claims of right to reimbursement provided to the Plaintiff by third-party payors, and copies of, or sufficient written HIPAA authorization to obtain, documentation of payments made by a third party for medical services received or premiums paid to obtain such payment. Information obtained pursuant to HIPAA shall not be used or disclosed for any purpose other than this litigation or proceeding.",
    "All documents identified or referred to in the answers to Interrogatory #26.",
    "A copy of any nonprivileged statement, as defined in Practice Book Section 13-1, of any party in this lawsuit concerning this action or its subject matter.",
    "Any and all photographs or recordings identified in response to Interrogatory #32.",
    "A copy of all records of blood alcohol testing or drug screens referred to in the answer to Interrogatory #34, or a signed authorization sufficient under HIPAA or the Public Health Service Act, whichever applies, to obtain them. Information obtained pursuant to those laws shall not be used or disclosed for any purpose other than this litigation or proceeding.",
    "A copy of every recording of surveillance material discoverable under Practice Book Section 13-3 (c), by film, photograph, video, audio or any other digital or electronic means, of any party concerning this lawsuit or its subject matter, including any transcript.",
)

# Form 205 is a document-production workflow, not an interrogatory. Keyword
# matches are search leads only and NEVER establish production, responsiveness,
# privilege, waiver, or legal sufficiency.

PRODUCTION_STATUSES = frozenset({
    "REVIEW_REQUIRED", "IDENTIFIED_NOT_PRODUCED", "PRODUCED_CONFIRMED",
    "NO_RESPONSIVE_CONFIRMED", "WITHHELD_FOR_ATTORNEY_REVIEW", "AUTHORIZATION_REVIEW",
})

# Distinctive search terms; deliberately not a legal determination.
SEARCH_TERMS = {
    1: ("hospital", "emergency department", "er visit", "medical release", "hipaa"),
    2: ("physician", "orthoped", "physical therapy", "medical report", "treatment", "hospital", "provider"),
    3: ("employer", "wage", "payroll", "salary", "employment", "work absence"),
    4: ("tax return", "w-2", "1040", "income tax"),
    5: ("vehicle repair", "property damage", "body shop", "collision estimate", "repair invoice"),
    6: ("medical bill", "hospital bill", "itemized billing", "invoice", "billing statement"),
    7: ("expense", "receipt", "out-of-pocket", "transportation reimbursement"),
    8: ("insurer", "explanation of benefits", "third party", "reimbursement", "lien", "payer"),
    9: ("settlement release", "settlement agreement", "covenant not to sue"),
    10: ("witness statement", "recorded statement", "statement of plaintiff", "insurance statement"),
    11: ("photograph", "photo log", "dashcam", "scene image", "video recording"),
    12: ("toxicology", "blood alcohol", "drug screen", "ethanol test"),
    13: ("surveillance recording", "surveillance video", "surveillance footage"),
}


def build_production_review(form_items, documents, previous=None):
    """Create 13 review slots. No automatic affirmative production responses."""
    previous = previous or {}
    slots = {}
    for item in form_items:
        number = item.number
        terms = SEARCH_TERMS[number]
        candidates = []
        for document in documents:
            matched = []
            evidence = []
            for segment in document.segments:
                found = [term for term in terms if term in segment.text.lower()]
                if found:
                    matched.extend(found)
                    if len(evidence) < 3:
                        evidence.append({
                            "page": segment.page, "segment_id": segment.segment_id,
                            "quote": segment.text[:400], "ocr_sourced": segment.ocr_sourced,
                        })
            # Filename is only an additional search hint, not proof of contents.
            filename_hits = [term for term in terms if term in document.filename.lower().replace("_", " ")]
            if matched or filename_hits:
                candidates.append({
                    "source_id": document.source_id, "filename": document.filename,
                    "sha256": document.sha256, "pages": document.pages,
                    "matched_terms": sorted(set(matched + filename_hits))[:7],
                    "passages": evidence,
                })
        prior = previous.get(item.item_id, {})
        # A changed packet invalidates any previous declaration that the
        # documents were actually produced; preserve the notes for review.
        slots[item.item_id] = {
            "item_id": item.item_id, "number": number, "request": item.text,
            "candidates": candidates,
            "status": "REVIEW_REQUIRED",
            "response": str(prior.get("response", ""))[:50000],
            "reviewer_notes": str(prior.get("reviewer_notes", ""))[:10000],
            "bates_range": str(prior.get("bates_range", ""))[:300],
            "selected_sources": [],
            "review_reset": bool(prior),
            "review_warning": "Candidate files are unverified search leads. Attorney must verify responsiveness, privilege, and actual production.",
        }
    return slots
