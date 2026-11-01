# Inquisitio 0.5.2 - Form 205 production-review extension

**New:** Every Form 202 personal-injury matter now includes a Form 205 tab with all 13 official 2026 Connecticut Requests for Production. It supplies potential PDF search leads, human-controlled production statuses, selected source files, manual Bates references, and attorney-entered responses. It does not auto-claim compliance, absence of documents, privilege, actual service, or Bates assignment. Word/PDF exports include the 13 responses as attorney-review drafts. Legacy 202 matters open with a new, unconfirmed Form 205 workspace; reprocessing their evidence is recommended.

See `FORM205_RELEASE_AND_TEST_GUIDE.md` and the separate fictional-test ZIP for exact steps. **Form 207 remains available and unchanged.**

# Inquisitio 0.5.1 release candidate

Inquisitio turns a PDF evidence packet and an optional `case_record.json` into a review workspace for Connecticut Practice Book Forms 202, 205 (paired with 202), and 207. It drafts only from validated PDF quotations or named case-record fields, exposes conflicts and missing information, and exports editable Word and PDF work product.

## Open on an Apple Silicon Mac

1. Extract the entire ZIP in Finder.
2. Double-click `Inquisitio.app`. If macOS asks for confirmation, choose **Open**. `START_INQUISITIO_MAC.command` remains as a fallback launcher.
3. Wait for the browser workspace to open. Keep the launcher window open while working.
4. Create a matter, choose Forms 202+205 or Form 207, add at least one PDF, optionally select `case_record.json`, and choose **Build response workspace**.
5. Review every draft and citation. Edited text is marked `EDITED`; only an explicit reviewer action produces `APPROVED`.
6. Use **Replace evidence** when the packet changes, then export Word or PDF.

No Python, pip, Docker, cloud service, external LLM, or Terminal command is required. The included Apple Silicon runtime and dependencies are installed privately from hash-checked local files. This package targets macOS 11 or newer. It is ad-hoc signed, not Apple-notarized.

## Evidence rules

- The only slot statuses are `EMPTY`, `DRAFT`, `EDITED`, `APPROVED`, `POTENTIAL_CONFLICT`, and `REQUIRES_CLIENT`.
- `NOT_IN_EVIDENCE` is a reason on an empty slot, never generated answer text.
- A generated answer always carries a validated PDF quotation or a citation such as `[Case record: client.birthDate]`.
- Conflicting values remain blank until a reviewer resolves them.
- A packet that names other people but not the responding party blocks automatic drafting.
- Replacing evidence rebuilds from the replacement packet; it does not retain an old evidence-backed answer.
- Concurrent browser edits use record revisions. A stale tab receives a visible conflict instead of silently overwriting newer work.

The optional case record must match the exact nested schema in `case_record.example.json`. Empty strings and `null` mean unknown, never not applicable. Intake rejects invalid JSON, an unsupported field, an incorrect field type, any non-PDF evidence file, or a packet with zero PDFs before creating a matter.

## Verified development packet

The included nine-page Okonkwo corpus contains two PDFs. In a clean matter, v0.5.1 produced 116 fact observations, 31 cited drafts, one visible DOB conflict, 49 empty slots with reasons, 85 validated citation references, and zero generated answers without a citation. The earlier v0.4.2 reference was 23 populated fields and 71 citation references; the eight additional drafts are evidence-bounded partial responses documented in `CHANGE_RECORD.md`.

The DOB slot presents both `05/30/1979` and `05/03/1979` and makes no automatic choice. The generated license, residence, treatment, provider, and employment responses retain source document ID, filename, actual PDF page, exact quotation, passage ID, and SHA-256 fingerprint.

Form 207 was independently exercised on a two-page fictional regression fixture: 19 facts, 38 populated responses, 40 validated citations, and 17 empty slots.

## Release status

This is a verified release candidate, not a production-acceptance claim. Ninety automated tests and HTTP end-to-end validation passed in the Linux build environment. The required seven-page October 20 corpus was not included, so its exact 25-fact/3-draft run could not be reproduced or fingerprinted. A physical Apple Silicon Mac and browser screenshot tooling were also unavailable. Tests B and I, and the requested visual proof, therefore remain open. See `TEST_REPORT.md` and `ROOT_CAUSE_REPORT.md`.

The detailed evidence workspaces, all-field CSV comparisons, block logs, Word/PDF exports, and counts are under `verification/0.5.1-final/`. No fixture is preloaded into a user's live matter list.


### Adding evidence in batches (0.5.2)

At matter creation, select the PDFs in one folder, then select again to add PDFs from another folder. The running list displays everything queued and lets you remove individual PDFs before processing. Click Build response workspace after all evidence PDFs are queued. Existing matters have a separate Update evidence packet picker with the same multi-batch staging. Keep Add to packet selected to preserve the existing packet, then click Upload and reprocess.
