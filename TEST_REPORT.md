# Inquisitio 0.5.0 verification report

Date: 2026-10-20 UTC  
Decision: **REJECTED FOR FINAL ACCEPTANCE; suitable for supervised release-candidate evaluation**

The application changes were executed, not merely written. Final acceptance remains blocked by missing external evidence: the exact seven-page October 20 corpus, visual browser capture, and a clean supported Apple Silicon Mac.

## Executed results

| Test | Result |
| --- | --- |
| Automated regression suite | PASS: 90 tests |
| Python/source and launcher syntax | PASS |
| Deterministic answer payload, same packet twice | PASS: byte-identical canonical answer JSON |
| Test A, supplied nine-page Okonkwo baseline | PASS: 2 PDFs, 9 pages, 116 facts, 31 populated, 85 validated citation references, 1 DOB conflict |
| Test B, exact seven-page October 20 failure | BLOCKED: corpus not supplied; no substituted input used |
| Test C, contradictory values | PASS: both sources displayed, blank response, `POTENTIAL_CONFLICT` |
| Test D, insufficient/replaced evidence | PASS: stale draft removed or downgraded; replacement is transactional |
| Test E, cross-matter isolation | PASS: independent matter directories and replacement tests |
| Test F, answer composition | PASS on supplied fixtures; irrelevant pleading language and wrong-party values excluded |
| Test G, Form 202 exports | PASS: 81 response slots plus 13 production requests; Word render and PDF text/count checks passed |
| Test H, Form 207 regression | PASS: 55 slots, 38 populated, 40 validated citations |
| Test I, clean supported Mac double-click | NOT RUN: no physical Mac in the build environment |
| Browser visual proof | NOT RUN: Playwright/Chromium unavailable and package download was blocked |

## Development evidence

The Okonkwo result contains 14 fully supported drafts, 16 supported partial drafts, one supported not-applicable draft, one conflict, and 49 empty fields. Every non-empty generated response has at least one independently validated citation. The exact field-by-field result is `verification/0.5.0-final/Okonkwo_all_fields.csv`; source blocks and validation data are in the adjacent JSON files.

The final Word export was rendered to images and visually inspected across all 25 pages. Headings, response text, citations, review markers, and the transition to production requests were readable without overlap or clipping. The PDF export contains 16 letter-sized pages. Application screenshots are not represented as completed proof.

## Residual risks

- The seven-page failure may involve different PDFs, incorrect metadata, stale state, or another runtime-specific condition. Its exact root cause cannot be established without those files and original matter record.
- The Finder wrapper, private runtime setup, quarantine handling, and ad-hoc code signing are syntax- and structure-checked but not executed on macOS here.
- The package is not notarized. Organization security policy may require a signed/notarized build.
- Local OCR helpers exist, but scanned-page accuracy depends on local Tesseract/Ghostscript availability and should be checked against the firm's actual scans.

Final acceptance requires running Tests B and I and capturing the graphical workflow on the actual packet. A failure in either keeps the build rejected.
