# Inquisitio 0.4.2 verification

The final pytest run executed **71 tests: 71 passed in 17.48 seconds** on Linux with Python 3.12.14. Full output is in `verification/pytest_results.txt`.

Coverage includes split labels and values, wrapped addresses, multiple header fields on one line, two-column and multi-operator tables, name variants and ambiguous initials, DOB/address conflicts, date normalization, exact quote/hash tampering, interactive fields, fragmented/out-of-order PDF text, real OCRmyPDF, real pytesseract fallback, a scanned entry beside a native printed label, latest-treatment chronology, manual-edit conflict reprocessing, every official form target, and the supplied development packet. Existing storage, upload, export and attorney-approval tests also passed.

Four original test expectations were changed to reflect the requested behavior: source classification no longer discards explicit facts; explicit non-applicability populates a cited response; and silence remains no responsive evidence. The original failure output is retained in historical logs. Old tests used short one-line examples and did not establish that the supplied PDF layouts worked.

The new mixed-page OCR test initially failed: OCR transcribed the native label DOB as "sop" while reading the date correctly. The targeted correction uses the native label and nearby OCR value and retains both source blocks. The failing output and the passing correction output are retained. The OCRmyPDF failure used in the fallback test is deliberate; its exact error is asserted and retained by the extraction code.

The unchanged source was run on the supplied 2-PDF, 9-page Okonkwo packet before edits. Baseline: 3 facts, 0 populated responses, 0 citations, 81 unresolved. The final real HTTP upload/extraction/export run returned: 116 facts, 23 populated responses, 71 validated citation references from 47 distinct passages, and 66 questions needing evidence or review. Citations were independently checked against the original PDF page text, page boundaries, party-attribution text and SHA-256 hashes. All 81 response fields occur in both exports. DOB remains blank with both conflicting dates shown.

A separate, clearly fictional Form 207 validation matter was processed through the same HTTP pipeline: 19 facts, 38 populated fields (12 supported drafts and 26 explicit not-applicable responses), 40 validated references and 17 unresolved fields. Both exports contain all 55 fields. This is regression verification, not an independent law-firm acceptance test.

The application health endpoint returned version 0.4.2, and the served HTML/JavaScript were checked for the corrected insertion notice and OCR citation label. Native launchers, signed/notarized builds, actual handwriting recognition and live-browser UI interaction were not executed. The user's separate private acceptance packet was not available.
