# Inquisitio 0.5.1 - Form 205 review and mock evidence

## What is added

The 2026 Connecticut Practice Book Form 205 has 13 numbered production requests. The exact question texts are extracted from the packaged official Connecticut Practice Book PDF (pages 625-626 of the bundled PDF). The existing v0.5.0 application appended Form 205 REQUESTS to Form 202 exports, but never tracked Form 205 responses or verified document-production claims. This release adds a real, separate Form 205 review screen **paired with each Form 202 case**. Form 207 is not changed.

Each request begins as REVIEW_REQUIRED with a blank response, no assigned Bates number and no selected evidence. The program searches PDFs for possible supporting passages and shows the exact source page/segment; search matches are **not proof** that a document is responsive or has been provided. The attorney chooses the relevant evidence, writes or approves the response, and confirms status. `PRODUCED_CONFIRMED` requires a manual response, selected uploaded PDFs, and a Bates range. `NO_RESPONSIVE_CONFIRMED` requires a reviewer explanation and zero selected PDFs. Other statuses remain pending review. Privilege and objections are solely attorney decisions.

**Important:** Bates text and a reviewer flag are not independent evidence of service. The software does not deliver discovery to opposing counsel, validate authorizations, convert synthetic photos to genuine records, or certify production completeness.

When any additional PDFs are uploaded or evidence is replaced, all Form 205 production statuses reset to REVIEW_REQUIRED, previously selected file IDs are cleared, and attorney notes and draft text survive for revalidation. Existing Form 202 answers use their preexisting separate process.

## Start on a Mac (no commands)

1. Extract the new ZIP into a **new** folder; do not merge it into v0.5.0.
2. Double-click `Inquisitio.app`; the included launcher and bundled offline dependencies are preserved. The app opens in the browser.
3. Verify header says Inquisitio 0.5.1.
4. Choose **Forms 202 + 205**, enter the Rivera mock matter, upload all PDFs from `FORM202_UPLOAD_ONLY` and `FORM205_UPLOAD_ONLY` in the separate mock ZIP, then click **Build response workspace**.
5. Switch between **Form 202 - Interrogatories** and **Form 205 - Document Production (13)**. Review possible evidence, then export Word/PDF and the traceability report.
6. Do not upload `DO_NOT_UPLOAD_ANSWER_KEYS`. Those are for independent scoring.

The `ONE_FILE_PER_CASE_QUICK_TEST/FORM_202_PLUS_205_ALL_EVIDENCE_COMBINED.pdf` file can be used instead for a quick single-upload test. The separate per-document upload is better for filename and document-level tracing.

## Acceptance checks

- Form 202 retains all 81 answer slots; Form 207 retains all 55.
- Form 205 shows exactly 13 official requests and a separate human-controlled production state for each.
- No Bates number or claimed production is automatically inserted.
- Candidates list exact PDF page, segment and excerpt, with a filename and SHA-256 in the trace report.
- Invalid production confirmations are rejected by the local API.
- Uploading more PDF evidence resets production confirmation; prior notes remain.
- Word/PDF exports contain 13 production responses (attorney-review drafts).
- Missing or incomplete tax, toxicology and surveillance evidence is never presumed satisfied.

## Scope and verification

The add-on uses the existing application architecture and libraries. No cloud AI, new recurring infrastructure, or database migration is required; Form 205 review is persisted alongside existing local case JSON and follows the same revision-locking model. The primary impact is to the source-form parser, Form 202 workspace, case persistence and Word/PDF exports. Original v0.5.0 tests and Form 207 workflows remain regression targets.

Local Linux tests do not prove that the Finder launcher, Apple Silicon runtime bootstrap, browser display or Mac ad-hoc signatures work on a physical Mac. The release is an acceptance candidate until tested on the target Mac and reviewed by Connecticut counsel. The test PDFs and all mock personal details are fictional and must never be filed or served.
