# 0.5.1 Change Record - Form 205

CHANGE: Added a Form 205 document-production review workspace for Form 202 cases, with evidence-search leads, reviewer-controlled response/status, and linked Word/PDF/traceability exports.
CAUSE: v0.5.0 printed 13 Form 205 REQUESTS in the output but did not allow responses, Bates tracking or production decisions inside the application.
TYPE: Missing user-facing feature; without it, the output appears complete but Form 205 responses remain generic placeholders.
SIMPLER OPTION REJECTED: Adding only editable placeholders to Word output would bypass evidence traceability and case revision safeguards.
TOUCHES: 202 case JSON gains optional `production` review slots; Form 205 text extracted from packaged official Practice Book PDF; server PUT/GET, exporter and local HTML/JS UI; Forms 202/207 answer generation unchanged.
NEW COST: No new third-party dependencies or cloud services.
TESTED BY: Explicit Form 205 parser, local status validation/reprocessing, 14-PDF fictional integration, 31 pages, Word/PDF/traceability output, and existing related regression cases. Physical Apple Silicon launch and end-user browser review remain unverified.
VERIFY IN USE: Open the new app, confirm 0.5.1, create a 202+205 case, inspect 13 requests, attempt to mark one produced without evidence/Bates and observe rejection, confirm production reset after reprocessing, inspect both exports.
SEE IT: `inquisitio/production.py`, `inquisitio/server.py`, `inquisitio/exporter.py`, `inquisitio/forms.py`, `web/app.js`, `web/index.html`, `web/styles.css`, `tests/test_production.py`, `tests/test_production_api.py`, `verification/0.5.1/`.

# Change record: 0.4.3 to 0.5.0

| Area | Before | 0.5.0 |
| --- | --- | --- |
| Intake | PDF-only; no record overlay | Transactional PDF packet plus optional strict `case_record.json` |
| Matter integrity | No packet-level identity gate | Per-document party names and PASS/WARNING/BLOCKED decision |
| Replacement | Append-oriented | Explicit add or replace; replacement invalidates old generated answers |
| Reviewer state | Split legacy engine statuses | Exactly six required statuses with safe migration |
| Concurrent edits | Last write silently won | Revision precondition and visible HTTP 409 conflict |
| Source traceability | PDF citations | PDF citations plus named case-record field citations |
| Form 202 baseline | 23 populated, 71 citation references | 31 populated, 85 citation references, same 116 facts and DOB conflict |
| Exports | Form responses only | 81 response slots followed by 13 production requests |
| Launch | `.command` entry point | Finder `Inquisitio.app` wrapper plus retained fallback |

The eight added Okonkwo drafts are qualified partials for questions 11, 12, 14(a-e), and 23(e). They state only what the cited record establishes, explicitly identify the unresolved conclusion or amount, and do not calculate a lost-wage total or assert permanent disability.

Readable unified source changes are in `verification/source_changes_0.5.0.diff`. The full corrected evidence-to-response output is in `verification/0.5.0-final/Okonkwo_all_fields.csv`; it includes every Form 202 slot, answer, status, source, page, quotation, and remaining-gap reason.


## 0.5.2 - Evidence selection fixed

Cause: the HTML multiple input supports selecting many files at once, but each new dialog selection replaced its FileList; the drop handler also overwrote previous files.
Change: introduced two in-memory queues (new matter and later reprocessing), accumulation, duplicate suppression, accessible file removal, and clear controls. Requests now use queue contents rather than the latest FileList.
Affected: web/index.html, web/app.js, web/styles.css, runtime version metadata, and documentation. No changes to evidence extraction, Form 205 review semantics, persistence, or exports. No new dependency.
Verification: see verification/0.5.2-upload-checks.txt (browser navigation was blocked by administrator policy; no visual screenshot was obtained).
