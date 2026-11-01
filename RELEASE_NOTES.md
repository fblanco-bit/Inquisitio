# Inquisitio 0.5.2 - Form 205 Review Extension

- Official 2026 Connecticut Practice Book Form 205 has all 13 requests in a new tab paired with personal-injury Form 202.
- PDF page/segment and filename search leads are shown separately from human confirmation of production; no automatic statements of compliance or Bates numbers.
- Production states and notes persist with the case and use revision-safe local updates. Evidence additions/replacements invalidate previous production confirmations.
- Word and PDF response exports now contain real Form 205 response slots; a separate traceability report documents candidate file hashes, page excerpts, selected files, reviewer states, and Bates data.
- New fictional Form 205 mock PDFs, field-by-field acceptance key and combined 31-page Form 202+205 evidence packet in `MOCK_TEST_SUITE/`.
- Existing Form 202 and Form 207 workflows remain enabled. No new third-party runtime dependencies were added.
- No independent verification of actual service, privilege status, document completeness, Mac launch operation, or lawyer acceptance is claimed.

# Inquisitio 0.5.0

Release candidate implementing the October 20 evidence-integrity and Form 202 prototype requirements.

- Adds transactional intake for PDFs plus an optional, strictly validated `case_record.json`.
- Stores matter-local document IDs, filenames, page counts, upload timestamps, SHA-256 fingerprints, extracted party names, and identity results.
- Blocks drafting on a material party mismatch and distinguishes that condition from an absent identity.
- Replaces legacy response states with the required six-state model and safely migrates existing records.
- Produces 31 cited evidence drafts on the supplied nine-page Okonkwo packet while retaining its visible DOB conflict.
- Adds named-field case-record citations and case-record/evidence conflict detection.
- Makes evidence replacement transactional and discards stale generated output.
- Adds optimistic revision checks so stale browser tabs cannot silently overwrite edits.
- Adds all 13 production requests after the 38 Form 202 interrogatories in Word and PDF exports.
- Removes per-response review markers only after explicit approval.
- Adds a double-clickable Finder `Inquisitio.app` wrapper while retaining the self-contained offline launcher.
- Adds regression tests for schema rejection, transactional intake, identity blocking, replacement, concurrency, citations, exports, OCR fallback, and deterministic answer output.

No new production library, hosted service, database, usage fee, or cloud dependency was introduced. The exact seven-page failed packet and a physical Mac were unavailable; those acceptance checks remain open.


## 0.5.2 - Multi-batch evidence selection correction

- The new-matter and existing-matter evidence pickers accumulate PDFs across repeated file-dialog selections; drag-and-drop adds to the same new-matter queue.
- Every queued file appears by filename with a Remove control; Clear all resets a batch. Identical queued files are skipped.
- Building or reprocessing sends all queued files in one request, without changing the evidence extraction, Form 202/205/207 logic, or Word/PDF templates.
- Existing-matter updates still default to Add to packet, not Replace entire packet.
- This source change does not introduce dependencies or alter the offline Mac runtime; physical Mac launcher testing remains unverified.
