const state = { case: null, filter: "ALL", search: "", selected: null, dirty: false, editGeneration: 0, view: "202", docView: "form" };
let autosaveTimer = null;
let savingPromise = null;
const statuses = [
  "EMPTY", "DRAFT", "EDITED", "APPROVED", "POTENTIAL_CONFLICT", "REQUIRES_CLIENT"
];
const labels = {
  EMPTY: "Empty",
  DRAFT: "Cited draft",
  EDITED: "Edited",
  APPROVED: "Approved",
  POTENTIAL_CONFLICT: "Potential conflict",
  REQUIRES_CLIENT: "Requires client"
};

const byId = id => document.getElementById(id);
const escapeHtml = value => String(value ?? "").replace(/[&<>'"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"}[c]));

function toast(message) {
  const node = byId("toast"); node.textContent = message; node.classList.add("show");
  clearTimeout(toast.timer); toast.timer = setTimeout(() => node.classList.remove("show"), 2400);
}

// Separate queues preserve PDF selections across multiple file-dialog sessions.
// Browser file inputs ordinarily replace, rather than append, their FileList.
const stagedEvidence = { initial: [], update: [] };
function fileIdentity(file) { return `${file.name}\u0000${file.size}\u0000${file.lastModified}`; }
function renderStagedFiles(kind) {
  const files = stagedEvidence[kind];
  const initial = kind === "initial";
  const list = byId(initial ? "pendingEvidenceList" : "pendingUpdateList");
  const summary = byId(initial ? "fileSummary" : "updateFileSummary");
  const clear = byId(initial ? "clearEvidenceButton" : "clearUpdateButton");
  summary.textContent = files.length ? `${files.length} PDF${files.length === 1 ? "" : "s"} queued - select again to add more` : (initial ? "No files selected" : "No additional PDFs selected");
  clear.hidden = files.length === 0;
  list.replaceChildren();
  files.forEach((file, index) => {
    const row = document.createElement("li");
    const name = document.createElement("span");
    name.textContent = file.name;
    name.title = file.name;
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "file-remove";
    remove.textContent = "Remove";
    remove.setAttribute("aria-label", `Remove ${file.name}`);
    remove.addEventListener("click", () => { files.splice(index, 1); renderStagedFiles(kind); });
    row.append(name, remove);
    list.append(row);
  });
}
function addStagedFiles(kind, items) {
  const files = stagedEvidence[kind];
  let duplicates = 0;
  let invalid = 0;
  for (const file of items) {
    if (!/\.pdf$/i.test(file.name)) { invalid++; continue; }
    if (files.some(existing => fileIdentity(existing) === fileIdentity(file))) { duplicates++; continue; }
    files.push(file);
  }
  renderStagedFiles(kind);
  if (invalid) toast(`${invalid} non-PDF file(s) skipped.`);
  else if (duplicates) toast(`${duplicates} already-selected PDF(s) skipped.`);
}
function clearStagedFiles(kind) { stagedEvidence[kind].length = 0; renderStagedFiles(kind); }
byId("evidenceFiles").addEventListener("change", event => {
  addStagedFiles("initial", [...event.currentTarget.files]);
  event.currentTarget.value = "";
});
byId("additionalEvidence").addEventListener("change", event => {
  addStagedFiles("update", [...event.currentTarget.files]);
  event.currentTarget.value = "";
});
byId("clearEvidenceButton").addEventListener("click", () => clearStagedFiles("initial"));
byId("clearUpdateButton").addEventListener("click", () => clearStagedFiles("update"));
const dropZone = byId("dropZone");
["dragenter", "dragover"].forEach(event => dropZone.addEventListener(event, e => { e.preventDefault(); dropZone.classList.add("dragging"); }));
["dragleave", "drop"].forEach(event => dropZone.addEventListener(event, e => { e.preventDefault(); dropZone.classList.remove("dragging"); }));
dropZone.addEventListener("drop", e => addStagedFiles("initial", [...e.dataTransfer.files]));
renderStagedFiles("initial");
renderStagedFiles("update");

byId("intakeForm").addEventListener("submit", async event => {
  event.preventDefault();
  const form = event.currentTarget;
  const button = byId("buildButton");
  const files = [...stagedEvidence.initial];
  if (!files.length) return toast("Add at least one evidence PDF.");
  button.disabled = true; button.textContent = "Reading evidence...";
  const started = Date.now();
  const progressTimer = setInterval(() => {
    const seconds = Math.max(1, Math.floor((Date.now() - started) / 1000));
    byId("intakeStatus").textContent = `Reading evidence: ${seconds}s elapsed. Large files may take several minutes.`;
  }, 1000);
  byId("intakeStatus").textContent = "Reading evidence: extracting page-level passages.";
  const data = new FormData();
  data.append("form_id", new FormData(form).get("form_id"));
  data.append("case_name", new FormData(form).get("case_name"));
  const metadata = {};
  ["court", "docket_number", "response_date", "plaintiff", "defendant", "judicial_district", "responding_party_role", "interrogating_party"].forEach(key => metadata[key] = new FormData(form).get(key));
  data.append("metadata", JSON.stringify(metadata));
  files.forEach(file => data.append("evidence", file, file.name));
  const caseRecord = byId("caseRecordFile").files[0];
  if (caseRecord) data.append("case_record", caseRecord, caseRecord.name);
  try {
    const response = await fetch("/api/cases", {method: "POST", body: data});
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "Evidence processing failed.");
    state.case = result; state.dirty = false; renderWorkspace();
  } catch (error) {
    byId("intakeStatus").textContent = error.message;
  } finally {
    clearInterval(progressTimer);
    button.disabled = false; button.textContent = "Build response workspace";
  }
});

function answerEntries() { return Object.entries(state.case.answers); }
function formItems() { return state.case.form.items; }
function itemById(id) { return formItems().find(item => item.item_id === id); }

function renderWorkspace() {
  byId("intakeView").hidden = true; byId("workspaceView").hidden = false; byId("workspaceActions").hidden = false;
  byId("caseName").textContent = state.case.case_name;
  byId("caseForm").textContent = state.case.form_id === "202" ? "Forms 202 + 205" : `Form ${state.case.form_id}`;
  const paired = state.case.form_id === "202" && !!state.case.production;
  byId("formTabs").hidden = !paired;
  if (!paired) state.view = "202";
  setActiveView();
  byId("formTitle").textContent = state.case.form.title;
  const summary = state.case.summary;
  byId("matterStats").innerHTML = [["Documents", summary.documents], ["Pages", summary.pages], ["Facts", summary.facts || 0], ["Responses", summary.items], ["Approved", summary.approved || 0]]
    .map(([k,v]) => `<div><dt>${k}</dt><dd>${v}</dd></div>`).join("");
  const integrity = state.case.matter_integrity || {status: "WARNING", message: "Matter identity has not been evaluated."};
  byId("integrityStatus").className = `integrity-status ${integrity.status.toLowerCase()}`;
  byId("integrityStatus").innerHTML = `<b>${escapeHtml(integrity.status === "PASS" ? "Identity matched" : integrity.status === "BLOCKED" ? "Drafting blocked" : "Identity review")}</b><span>${escapeHtml(integrity.message)}</span>`;
  renderFilters(); renderQuestions(); renderFormDoc(); renderProduction(); updateProgress();
  if (summary.ocr_required?.length) toast(`${summary.ocr_required.length} document(s) require OCR.`);
}

async function loadRecentMatters() {
  try {
    const response = await fetch("/api/cases");
    const result = await response.json();
    if (!result.cases?.length) return;
    byId("recentMatters").hidden = false;
    byId("recentMatterList").innerHTML = result.cases.slice(0, 8).map(record => `<button class="recent-matter" data-case="${record.case_id}" type="button">
      <strong>${escapeHtml(record.case_name)}</strong><span>Form ${record.form_id}</span><span>${escapeHtml((record.updated_at || "").slice(0, 10))}</span></button>`).join("");
    document.querySelectorAll("[data-case]").forEach(button => button.onclick = async () => {
      const caseResponse = await fetch(`/api/cases/${button.dataset.case}`);
      if (!caseResponse.ok) return toast("The matter could not be opened.");
      state.case = await caseResponse.json(); state.dirty = false; renderWorkspace();
    });
  } catch (_) { /* Recent matters are convenience only. */ }
}

function renderFilters() {
  const counts = answerEntries().reduce((result, [, answer]) => {
    result[answer.status] = (result[answer.status] || 0) + 1; return result;
  }, {});
  const entries = [["ALL", "All responses", formItems().length], ...statuses.map(status => [status, labels[status], counts[status] || 0])];
  byId("statusFilters").innerHTML = entries.map(([key, label, count]) =>
    `<button class="filter-button ${state.filter === key ? "active" : ""}" data-filter="${key}" type="button"><span>${escapeHtml(label)}</span><b>${count}</b></button>`).join("");
  document.querySelectorAll("[data-filter]").forEach(button => button.onclick = () => { state.filter = button.dataset.filter; renderFilters(); renderQuestions(); });
}

function renderQuestions() {
  const query = state.search.trim().toLowerCase();
  const visible = formItems().filter(item => {
    const answer = state.case.answers[item.item_id];
    if (state.filter !== "ALL" && answer.status !== state.filter) return false;
    return !query || `${item.prompt} ${item.text} ${answer.answer}`.toLowerCase().includes(query);
  });
  byId("questionList").innerHTML = visible.map(item => {
    const answer = state.case.answers[item.item_id];
    const label = item.label ? `${item.number}(${item.label})` : `${item.number}`;
    const engineStatus = answer.status;
    const approved = answer.status === "APPROVED";
    const actionLabel = answer.requires_revalidation ? "Revalidate edit" : approved ? "Approved" : "Approve";
    const detail = answer.evidence_outcome ? `<span>${escapeHtml(answer.evidence_outcome.replaceAll("_", " ").toLowerCase())}</span>` : "";
    const missing = answer.missing_information?.length ? `<div class="missing-info"><b>Missing information:</b> ${answer.missing_information.map(escapeHtml).join(", ")}</div>` : "";
    const conflicts = answer.conflicts?.length ? `<div class="conflict-info"><b>Conflict:</b> ${answer.conflicts.map(value => escapeHtml(value.description)).join("; ")}</div>` : "";
    return `<article class="question-row" data-item="${item.item_id}">
      <div class="question-head"><div><div class="question-number">${escapeHtml(label)}</div><p class="question-text">${item.prompt ? `<span class="question-prompt">${escapeHtml(item.prompt)}</span>` : ""}${escapeHtml(item.text)}</p></div>
      <div class="status-stack"><span class="status-badge">${escapeHtml(labels[engineStatus] || engineStatus)}</span>${detail}</div></div>
      <textarea class="answer-field" aria-label="Response to ${escapeHtml(label)}">${escapeHtml(answer.answer)}</textarea>
      ${missing}${conflicts}
      <div class="question-meta"><button class="evidence-link" type="button">Review evidence</button><span class="match-count">${(answer.supporting_citations || []).length} validated citation${(answer.supporting_citations || []).length === 1 ? "" : "s"}</span><button class="approval-button secondary" type="button" ${approved ? "disabled" : ""}>${actionLabel}</button></div>
    </article>`;
  }).join("") || `<p class="empty-state">No responses match this filter.</p>`;
  document.querySelectorAll(".question-row").forEach(row => {
    const id = row.dataset.item;
    row.querySelector("textarea").addEventListener("input", e => {
      const answer = state.case.answers[id]; answer.answer = e.target.value; answer.status = "EDITED"; answer.engine_status = "EDITED"; answer.approval = null; answer.requires_revalidation = answer.answer !== answer.generated_answer; row.querySelector(".approval-button").textContent = answer.requires_revalidation ? "Revalidate edit" : "Approve"; row.querySelector(".approval-button").disabled = false; markDirty();
    });
    row.querySelector(".approval-button").addEventListener("click", () => {
      const answer = state.case.answers[id];
      if (answer.requires_revalidation) { answer.revalidated = true; answer.requires_revalidation = false; }
      else { answer.status = "APPROVED"; answer.engine_status = "APPROVED"; }
      markDirty(); renderQuestions(); updateProgress();
    });
    row.querySelector(".evidence-link").addEventListener("click", () => showEvidence(id));
  });
}

function showEvidence(itemId) {
  state.selected = itemId;
  const item = itemById(itemId), answer = state.case.answers[itemId];
  byId("evidenceTitle").textContent = `${item.number}${item.label ? `(${item.label})` : ""} evidence`;
  const validated = answer.supporting_citations || [];
  const candidates = (answer.candidate_passages || []).filter(candidate => !validated.some(citation => citation.segment_id === candidate.segment_id));
  const citationHtml = citation => `<div class="citation">
    <div class="citation-meta"><b>${escapeHtml(citation.source_id || citation.filename)}</b><span>${citation.citation_kind === "case_record" ? escapeHtml(citation.citation_label) : `Page ${citation.page}${citation.ocr_sourced ? " · OCR-sourced" : ""}`}</span></div>
    <blockquote>${escapeHtml(citation.quote)}</blockquote>
    <div class="citation-terms">${escapeHtml(citation.evidence_classification || "Candidate passage")} · SHA-256 ${escapeHtml((citation.document_sha256 || "").slice(0, 12))}</div>
  </div>`;
  byId("evidenceBody").innerHTML = `${validated.length ? `<h3>Validated support</h3>${validated.map(citationHtml).join("")}` : ""}
    ${answer.missing_information?.length ? `<h3>Missing information</h3><p>${answer.missing_information.map(escapeHtml).join(", ")}</p>` : ""}
    ${answer.conflicts?.length ? `<h3>Conflicts</h3><p>${answer.conflicts.map(value => escapeHtml(value.description)).join("; ")}</p>` : ""}
    ${candidates.length ? `<h3>Candidate passages</h3>${candidates.map(citationHtml).join("")}` : ""}
    ${!validated.length && !candidates.length ? `<p class="empty-state">No potentially relevant passage was found. The answer remains unresolved.</p>` : ""}`;
  byId("evidenceBody").parentElement.classList.add("open");
}

const productionStatusOptions = [
  ["REVIEW_REQUIRED", "Review required"],
  ["IDENTIFIED_NOT_PRODUCED", "Potential documents identified - not produced"],
  ["PRODUCED_CONFIRMED", "Reviewer confirms produced (requires response, files, Bates)"],
  ["NO_RESPONSIVE_CONFIRMED", "Reviewer confirms no responsive documents"],
  ["WITHHELD_FOR_ATTORNEY_REVIEW", "Privilege / objection - attorney review"],
  ["AUTHORIZATION_REVIEW", "Authorization to be reviewed"],
];
function setActiveView() {
  const paired = state.case?.form_id === "202" && !!state.case.production;
  const production = paired && state.view === "205";
  const formDoc = !production && state.docView === "form";
  byId("show202Tab").classList.toggle("active", !production);
  byId("show205Tab").classList.toggle("active", !!production);
  byId("questionToolbar").hidden = !!production;
  byId("formDocTab").classList.toggle("active", formDoc);
  byId("worksheetTab").classList.toggle("active", !formDoc);
  byId("searchLabel").hidden = formDoc;
  byId("progressBar").parentElement.hidden = !!production;
  byId("formDocView").hidden = !formDoc;
  byId("questionList").hidden = !!production || formDoc;
  byId("productionView").hidden = !production;
  byId("statusFilters").hidden = !!production || formDoc;
  byId("productionRailNotice").hidden = !production;
}
byId("show202Tab").addEventListener("click", () => { state.view = "202"; setActiveView(); });
byId("show205Tab").addEventListener("click", () => { state.view = "205"; setActiveView(); renderProduction(); });
byId("formDocTab").addEventListener("click", () => { state.docView = "form"; setActiveView(); renderFormDoc(); });
byId("worksheetTab").addEventListener("click", () => { state.docView = "worksheet"; setActiveView(); renderQuestions(); });

// Completed-form view: the matter rendered as the pleading itself, in export
// order, with approval state and controls on each answer. Slots with no entered
// answer show the firm profile's template text (merge fields / stock answers),
// which passes through for Filevine and is never approvable.
const BLOCKED_FOR_APPROVAL = new Set(["EMPTY", "REQUIRES_CLIENT", "POTENTIAL_CONFLICT"]);
function renderFormDoc() {
  const host = byId("formDocView");
  if (!state.case) { host.innerHTML = ""; return; }
  const meta = state.case.metadata || {};
  const profile = state.case.firm_profile || null;
  const fallbacks = profile?.fallback_answers || {};
  const esc = escapeHtml;
  const parts = [];
  parts.push(`<div class="doc-caption">
    <div><b>DOCKET NO.: ${esc(meta.docket_number || "")}</b><b>${esc(meta.plaintiff || "Plaintiff")}</b><b>v.</b><b>${esc(meta.defendant || "Defendant")}</b></div>
    <div><b>SUPERIOR COURT</b><b>JUDICIAL DISTRICT OF ${esc(meta.judicial_district || "")}</b><b>AT ${esc(meta.court || "")}</b><b>${esc(meta.response_date || "")}</b></div>
  </div>`);
  parts.push(`<p class="doc-banner">ATTORNEY REVIEW DRAFT - NOT FOR SERVICE</p>`);
  const intros = profile
    ? [profile.intro, profile.definition, profile.instruction]
    : [`The undersigned submits the following responses to Connecticut Practice Book Form ${esc(state.case.form_id)}.`];
  intros.filter(Boolean).forEach(text => parts.push(`<p class="doc-intro">${esc(text)}</p>`));
  let lastNumber = null;
  for (const item of formItems()) {
    if (item.number !== lastNumber) {
      lastNumber = item.number;
      if (item.prompt) parts.push(`<p class="doc-question"><b>${item.number}.</b> ${esc(item.prompt)}</p>`);
    }
    if (item.label) parts.push(`<p class="doc-subpart"><b>(${esc(item.label)})</b> ${esc(item.text)}</p>`);
    else if (!item.prompt) parts.push(`<p class="doc-question"><b>${item.number}.</b> ${esc(item.text)}</p>`);
    const answer = state.case.answers[item.item_id] || {};
    const text = String(answer.answer || "").trim();
    const fallback = fallbacks[item.item_id] || "";
    const approved = answer.status === "APPROVED";
    const blocked = BLOCKED_FOR_APPROVAL.has(answer.status);
    const needsRevalidation = !!answer.requires_revalidation;
    let bodyHtml, badgeHtml, controls = "";
    if (text) {
      bodyHtml = `<span class="doc-answer-text">${esc(text)}</span>`;
      if (approved) {
        badgeHtml = `<span class="doc-badge approved">Approved</span>`;
      } else {
        badgeHtml = `<span class="doc-badge pending">Not approved</span>`;
        const disabled = blocked || needsRevalidation ? "" : "";
        controls = needsRevalidation
          ? `<button class="doc-action" data-act="revalidate" type="button">Revalidate edit</button>`
          : blocked ? "" : `<button class="doc-action" data-act="approve" type="button">Approve</button>`;
      }
    } else if (fallback) {
      bodyHtml = `<span class="doc-answer-template">${esc(fallback)}</span>`;
      badgeHtml = `<span class="doc-badge template">Firm template - not approvable</span>`;
    } else {
      bodyHtml = `<span class="doc-answer-template">[No response entered - attorney review required.]</span>`;
      badgeHtml = `<span class="doc-badge pending">Not approved</span>`;
    }
    const findings = [];
    if (blocked && answer.missing_information?.length) findings.push(`Resolve before approving - missing: ${answer.missing_information.map(esc).join(", ")}`);
    if (answer.conflicts?.length) findings.push(`Conflict: ${answer.conflicts.map(v => esc(v.description)).join("; ")}`);
    const findingHtml = findings.length ? `<div class="doc-finding">${findings.join("<br>")}</div>` : "";
    parts.push(`<div class="doc-answer" data-item="${item.item_id}">
      <p><b>ANSWER:</b> ${bodyHtml}</p>
      <div class="doc-answer-meta">${badgeHtml}${controls}<button class="doc-action secondary" data-act="edit" type="button">${text ? "Edit" : "Enter answer"}</button></div>
      ${findingHtml}
      <div class="doc-edit" hidden><textarea rows="3" aria-label="Edit response">${esc(answer.answer || "")}</textarea></div>
    </div>`);
  }
  if (state.case.form_id === "202" && state.case.production) {
    parts.push(`<h3 class="doc-section">REQUESTS FOR PRODUCTION</h3>`);
    if (profile?.production_intro) parts.push(`<p class="doc-intro">${esc(profile.production_intro)}</p>`);
    const productionFallbacks = profile?.production_fallbacks || {};
    Object.entries(state.case.production).forEach(([id, item], index) => {
      const response = String(item.response || "").trim();
      const fallback = productionFallbacks[id] || "";
      parts.push(`<p class="doc-question"><b>${index + 1}.</b> ${esc(item.request || "")}</p>
        <div class="doc-answer"><p><b>RESPONSE:</b> ${response ? `<span class="doc-answer-text">${esc(response)}</span>` : fallback ? `<span class="doc-answer-template">${esc(fallback)}</span>` : `<span class="doc-answer-template">[Production response not verified - attorney review required.]</span>`}</p>
        <div class="doc-answer-meta"><span class="doc-badge template">Edit production responses in the Form 205 tab</span></div></div>`);
    });
  }
  host.innerHTML = parts.join("");
  host.querySelectorAll(".doc-answer[data-item]").forEach(block => {
    const id = block.dataset.item;
    block.querySelectorAll(".doc-action").forEach(button => button.addEventListener("click", () => {
      const answer = state.case.answers[id];
      if (button.dataset.act === "edit") {
        const editor = block.querySelector(".doc-edit");
        editor.hidden = !editor.hidden;
        if (!editor.hidden) editor.querySelector("textarea").focus();
        return;
      }
      if (button.dataset.act === "revalidate") {
        answer.revalidated = true; answer.requires_revalidation = false;
      } else if (button.dataset.act === "approve") {
        answer.status = "APPROVED"; answer.engine_status = "APPROVED";
      }
      markDirty(); renderFormDoc(); updateProgress();
    }));
    block.querySelector(".doc-edit textarea").addEventListener("change", e => {
      const answer = state.case.answers[id];
      answer.answer = e.target.value; answer.status = "EDITED"; answer.engine_status = "EDITED";
      answer.approval = null; answer.requires_revalidation = answer.answer !== answer.generated_answer;
      markDirty(); renderFormDoc(); updateProgress();
    });
  });
}

function renderProduction() {
  if (!state.case?.production) { byId("productionList").innerHTML = ""; return; }
  const documents = state.case.documents || [];
  const items = Object.values(state.case.production).sort((a,b) => a.number - b.number);
  byId("productionList").innerHTML = items.map(item => {
    const candidateIds = new Set((item.candidates || []).map(v => v.source_id));
    const choices = documents.map(doc => {
      const matched = candidateIds.has(doc.source_id);
      const selected = (item.selected_sources || []).includes(doc.source_id);
      return `<label class="production-file"><input type="checkbox" data-source="${escapeHtml(doc.source_id)}" ${selected ? "checked" : ""}><span>${escapeHtml(doc.source_id)}: ${escapeHtml(doc.filename)}${matched ? " - Possible match" : " - Not matched"}</span></label>`;
    }).join("");
    const evidence = (item.candidates || []).slice(0, 6).map(candidate =>
      `<li><b>${escapeHtml(candidate.filename)}</b> (${escapeHtml(candidate.source_id)}) - possible match: ${escapeHtml(candidate.matched_terms.join(", "))}${(candidate.passages || []).slice(0,2).map(p => `<p>PDF page ${escapeHtml(p.page)}, ${escapeHtml(p.segment_id)}: &ldquo;${escapeHtml(p.quote)}&rdquo;</p>`).join("")}</li>`).join("");
    return `<article class="production-row" data-production="${escapeHtml(item.item_id)}">
      <div class="question-number">Form 205 - Request ${escapeHtml(item.number)} of 13</div>
      <p class="question-text">${escapeHtml(item.request)}</p>
      ${item.review_reset ? '<p class="production-warning">Evidence packet changed: previous production confirmation was reset.</p>' : ''}
      <details class="production-candidates"><summary>Possible matches (${(item.candidates || []).length}) - review exact PDF evidence</summary>
        ${evidence ? `<ul>${evidence}</ul>` : '<p>No keyword match. A reviewer must still check all documents and the complete case record.</p>'}</details>
      <label>Documents reviewer selects for this request (selection alone does not mean produced)<div class="production-files">${choices}</div></label>
      <div class="production-fields">
        <label>Reviewer production status<select class="production-status">${productionStatusOptions.map(([value,label]) => `<option value="${value}" ${item.status===value ? "selected" : ""}>${escapeHtml(label)}</option>`).join("")}</select></label>
        <label>Bates numbers (enter only verified actual production references)<input class="production-bates" maxlength="300" value="${escapeHtml(item.bates_range || "")}" placeholder="e.g., PLTF_0001-PLTF_0012"></label>
      </div>
      <label>Draft response / attorney-approved objection<textarea class="production-response" rows="3" placeholder="Attorney must write or confirm the response; not generated from keyword matches.">${escapeHtml(item.response || "")}</textarea></label>
      <label>Private attorney review notes<textarea class="production-notes" rows="2">${escapeHtml(item.reviewer_notes || "")}</textarea></label>
      <p class="production-warning">${escapeHtml(item.review_warning || "Reviewer verification required")}</p>
    </article>`;
  }).join("");
  document.querySelectorAll(".production-row").forEach(row => {
    const item = state.case.production[row.dataset.production];
    row.querySelector(".production-status").addEventListener("change", e => { item.status = e.target.value; markDirty(); });
    row.querySelector(".production-bates").addEventListener("input", e => { item.bates_range = e.target.value; markDirty(); });
    row.querySelector(".production-response").addEventListener("input", e => { item.response = e.target.value; markDirty(); });
    row.querySelector(".production-notes").addEventListener("input", e => { item.reviewer_notes = e.target.value; markDirty(); });
    row.querySelectorAll("[data-source]").forEach(box => box.addEventListener("change", () => {
      item.selected_sources = [...row.querySelectorAll("[data-source]:checked")].map(x => x.dataset.source);
      markDirty();
    }));
  });
}

function markDirty() {
  state.dirty = true; state.editGeneration += 1; byId("saveState").textContent = "Autosave pending";
  clearTimeout(autosaveTimer); autosaveTimer = setTimeout(() => saveResponses(false), 900);
}
function updateProgress() {
  const complete = answerEntries().filter(([, answer]) => answer.status === "APPROVED").length;
  byId("progressBar").style.width = `${Math.round(complete / formItems().length * 100)}%`;
}

async function saveResponses(showConfirmation = true) {
  if (!state.case) return false;
  clearTimeout(autosaveTimer);
  if (savingPromise) {
    await savingPromise;
    if (state.dirty) return saveResponses(showConfirmation);
    return true;
  }
  const button = byId("saveButton"); button.disabled = true;
  const editGeneration = state.editGeneration;
  const answers = JSON.parse(JSON.stringify(state.case.answers));
  savingPromise = (async () => {
   try {
    const response = await fetch(`/api/cases/${state.case.case_id}/answers`, {
      method: "PUT", headers: {"Content-Type": "application/json"}, body: JSON.stringify({answers, production: state.case.production || {}, revision: state.case.revision})
    });
    const result = await response.json();
    if (!response.ok) {
      if (response.status === 409) byId("saveState").textContent = "Conflict - reload matter";
      throw new Error(result.error || "Save failed.");
    }
    if (state.editGeneration === editGeneration) {
      state.case = result; state.dirty = false; byId("saveState").textContent = "Saved locally";
      if (showConfirmation) toast("Responses saved.");
    }
    return true;
   } catch (error) { byId("saveState").textContent = "Save failed"; toast(error.message); return false; }
  })();
  const saved = await savingPromise;
  savingPromise = null; button.disabled = false;
  if (state.dirty && state.editGeneration !== editGeneration) {
    clearTimeout(autosaveTimer); autosaveTimer = setTimeout(() => saveResponses(false), 300);
  }
  return saved && !state.dirty;
}

byId("saveButton").onclick = () => saveResponses(true);
byId("exportButton").onclick = async () => { if (!state.dirty || await saveResponses(false)) window.location.href = `/api/cases/${state.case.case_id}/export`; };
byId("pdfButton").onclick = async () => { if (!state.dirty || await saveResponses(false)) window.location.href = `/api/cases/${state.case.case_id}/pdf`; };
byId("traceButton").onclick = async () => { if (!state.dirty || await saveResponses(false)) window.location.href = `/api/cases/${state.case.case_id}/traceability`; };
byId("reprocessButton").onclick = async () => {
  const files = [...stagedEvidence.update];
  if (!files.length) return toast("Select one or more additional PDFs.");
  // D-002: flush any pending autosave first, as the export buttons do, so the
  // upload carries the current revision instead of colliding with our own save.
  if (state.dirty && !(await saveResponses(false))) return toast("Save your edits before reprocessing evidence.");
  const data = new FormData(); files.forEach(file => data.append("evidence", file, file.name));
  data.append("mode", byId("evidenceMode").value);
  data.append("revision", String(state.case.revision));
  const response = await fetch(`/api/cases/${state.case.case_id}/evidence`, {method: "POST", body: data});
  const result = await response.json();
  if (!response.ok) return toast(result.error || "Reprocessing failed.");
  clearStagedFiles("update");
  state.case = result; state.dirty = false; renderWorkspace(); toast("Evidence added and responses reprocessed.");
};
byId("newCaseButton").onclick = () => { if (state.dirty && !confirm("Discard unsaved changes?")) return; location.reload(); };
byId("deleteCaseButton").onclick = async () => {
  if (!state.case || !confirm(`Permanently delete ${state.case.case_name} and its evidence files?`)) return;
  const response = await fetch(`/api/cases/${state.case.case_id}`, {method: "DELETE"});
  if (!response.ok) return toast("The matter could not be deleted.");
  state.dirty = false; location.reload();
};
byId("questionSearch").addEventListener("input", e => { state.search = e.target.value; renderQuestions(); });
byId("inspectorClose").onclick = () => byId("evidenceBody").parentElement.classList.remove("open");
window.addEventListener("beforeunload", event => {
  if (!state.dirty) return;
  event.preventDefault(); event.returnValue = "";
});
loadRecentMatters();
