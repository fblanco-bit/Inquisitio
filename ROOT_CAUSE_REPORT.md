# Root-cause report

## Conclusion

The precise cause of the reported v0.4.3 result (2 PDFs, 7 pages, 25 facts, 3 drafts) is **not reproducible from the delivered inputs**. The package contains a different, nine-page Okonkwo fixture. The seven-page PDFs and original matter record were not attached, so their filenames, SHA-256 fingerprints, party identities, cached state, and before/after field output cannot be truthfully reconstructed.

The supplied nine-page corpus reproduces the established 116-fact baseline under both the original v0.4.3 code and corrected v0.5 path; it does not reproduce 25 facts or 3 drafts. Therefore the observed discrepancy cannot be attributed to a proven parser regression from the available evidence.

## File identity established

| ID | File | Pages | SHA-256 | Responding-party result |
| --- | --- | ---: | --- | --- |
| E-001 | `DEV_Evidence_1_Complaint_and_Crash_Report.pdf` | 4 | `a8fbeff96e38287d1b71f576d2d4e0e38b2cc5d83cc54058502f86d741c05e59` | Terrence Okonkwo matched |
| E-002 | `DEV_Evidence_2_Medical_and_Employer_Records.pdf` | 5 | `810b92317098292b0fed63966b37e897d4eff0a1f69da746959353c451d7a538` | Terrence Okonkwo matched |

Names detected in E-001 include Terrence James Okonkwo, Sofia Marques, and Anna Lindqvist. Names detected in E-002 include Terrence J. Okonkwo, Terrence Okonkwo, and T. Okonkwo. Full extraction records are in `verification/0.5.0-final/Okonkwo_workspace.json`.

## Actual defects found

1. Intake had no optional case-record channel, schema validation, or named-field citations.
2. The response model used legacy outcome-like states instead of the required six reviewer states.
3. Evidence could be appended without an explicit replace operation; replacement did not provide the required clean invalidation contract.
4. The server had no revision precondition, allowing two stale browser tabs to overwrite one another silently.
5. Document summaries did not expose a packet-level matter-identity decision capable of blocking generation.
6. Exports omitted the 13 production requests required after the 38 interrogatories.
7. Several evidence-supported partial Form 202 slots were left blank even though a precise, qualified draft could be cited without inventing missing values.

Information stopped at answer composition for the last category: responsive source segments and facts were present, but the slot builder returned no draft for the qualified partial. The correction adds narrowly registered slot composition using the existing facts and citations. It does not insert fixture literals or lower citation validation.

## Seven-page versus nine-page discrepancy

The corpora cannot be shown to be the same. The available corpus is exactly nine pages with the two hashes above; no seven-page PDF exists in the uploaded ZIP or companion files. The report also describes injuries inconsistent with the known Okonkwo packet, which is evidence that a different packet or matter association may have been involved, but that remains an inference rather than a verified cause.

Wrong-evidence defects cannot be assigned field by field without the missing corpus. The corrected application now makes such a condition observable: it records identities per PDF, warns on absent identity, blocks an affirmative mismatch, and never reuses a replaced packet's generated result.

## Correction selected

The smallest viable correction retained the deterministic local extraction, binding, storage, citation, and export architecture. It added integrity gates, explicit replacement, case-record overlay, canonical statuses, revision checks, and evidence-bounded slot builders. No database, framework, external model, cloud service, new production dependency, or recurring cost was introduced.

## Mandatory responses

1. **Exact root cause and reproduction:** the exact reported failure is indeterminate because its evidence and matter record are absent. The supplied nine-page run does not reproduce it. Concrete product defects found are listed above and are covered by tests.
2. **Were the corpora different?** They cannot be proven identical and their page counts differ. Only the nine-page filenames and hashes above are available; seven-page fingerprints cannot be invented.
3. **Wrong evidence versus code defects:** wrong evidence is plausible but unverified. Missing integrity controls, replacement invalidation, concurrency control, case-record support, canonical states, production export, and qualified partial mappings were verified code defects.
4. **Simplest correction:** preserve the architecture and add narrowly scoped validation, state, mapping, and export changes.
5. **Changed components:** `case_record`, response engine, server/intake, storage migration behavior, exporter/production inventory, web UI, launcher metadata, tests, and verification tooling.
6. **New libraries/services/costs:** none in production.
7. **Executed tests:** detailed individually in `TEST_REPORT.md`; 90 automated tests plus HTTP/export validation passed. Tests B, I, and browser capture were not run.
8. **Graphical verification:** open `Inquisitio.app`, create a clean matter, select the form, choose the PDFs and optional case record, build, inspect the integrity banner and citations, resolve/approve, then export.
9. **Code and before/after evidence:** see `CHANGE_RECORD.md`, `verification/source_changes_0.5.0.diff`, and `verification/0.5.0-final/Okonkwo_all_fields.csv`.
