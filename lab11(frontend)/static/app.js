const programSelect = document.getElementById("program");
const editionSelect = document.getElementById("edition");
const trackSelect = document.getElementById("track");
const submitButton = document.querySelector(
  '#ask-form button[type="submit"]'
);

let programs = [];
let uiState = "idle";
let lastResponse = null;
let lastAskPayload = null;
const copyButton = document.getElementById("copy-answer");
const copyFallback = document.getElementById("copy-fallback");
const form = document.getElementById("ask-form");
const question = document.getElementById("question");
const statusMessage = document.getElementById("ui-status");
const answerPanel = document.getElementById("answer-panel");
const answerBody = document.getElementById("answer");
const answerBadge = document.getElementById("answer-badge");
const answerContext = document.getElementById("answer-context");
const answerIntro = document.querySelector(".answer-intro");
const answerHighlights = document.getElementById("answer-highlights");
const responseDetails = document.getElementById("response-details");
const answerTiming = document.getElementById("answer-timing");
const responseTime = document.getElementById("response-time");
const processingTime = document.getElementById("processing-time");
const answerCitations = document.getElementById("answer-citations");
const citationsList = document.getElementById("citations-list");
const answerAnalysis = document.getElementById("answer-analysis");
const numberFormat = new Intl.NumberFormat("th-TH", { maximumFractionDigits: 20 });

function createElement(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
}

function trackLabel(track) {
  return {coop: "สหกิจศึกษา", nocoop: "ไม่สหกิจศึกษา", default: "แผนเดียว"}[track] || track;
}

// ใช้ text nodes แสดงคำตอบ/ข้อมูลเสมอ เพื่อให้ข้อความจาก API เป็นข้อความธรรมดา.
function appendAnswerText(element, text) {
  const values = /\d+(?:[.,]\d+)?\s*(?:หน่วยกิต|ช่องวิชา|วิชา|ปี|รายการ)/g;
  let cursor = 0;
  for (const match of text.matchAll(values)) {
    element.append(document.createTextNode(text.slice(cursor, match.index)));
    element.append(createElement("strong", "answer-number", match[0]));
    cursor = match.index + match[0].length;
  }
  element.append(document.createTextNode(text.slice(cursor)));
}

function resetResult() {
  lastResponse = null;
  copyButton.disabled = true;
  copyButton.textContent = "คัดลอกคำตอบ";
  copyFallback.hidden = true;
  copyFallback.querySelector("textarea").value = "";
  answerAnalysis.hidden = true;
  answerAnalysis.replaceChildren();
  answerIntro.textContent = "ข้อมูลสำหรับหลักสูตรและแผนการเรียนที่คุณเลือก";
  answerTiming.hidden = true;
  responseTime.textContent = "";
  processingTime.hidden = true;
  processingTime.textContent = "";
  answerCitations.hidden = true;
  citationsList.replaceChildren();
  document.getElementById("citations-description").textContent = "";
  answerContext.hidden = true;
  answerHighlights.hidden = true;
  answerHighlights.replaceChildren();
  responseDetails.hidden = true;
  responseDetails.open = false;
  responseDetails.querySelectorAll("details").forEach((details) => { details.open = false; });
  document.getElementById("rows-table").replaceChildren();
  document.getElementById("rows").textContent = "-";
  document.getElementById("sql").textContent = "-";
}

function renderEmptyResult(state, message) {
  const empty = createElement("div", "answer-empty");
  const icon = createElement("span", "answer-empty-icon");
  icon.setAttribute("aria-hidden", "true");
  empty.append(icon);
  empty.append(createElement("p", "answer-empty-title", {
    idle: "พร้อมช่วยค้นข้อมูลหลักสูตร",
    loading: "กำลังเตรียมคำตอบให้คุณ",
    error: "ยังแสดงคำตอบไม่ได้"
  }[state]));
  empty.append(createElement("p", "answer-empty-description",
    state === "idle" ? "เลือกหลักสูตรและพิมพ์คำถาม แล้วอ่านคำตอบได้ที่นี่" : message));
  answerBody.replaceChildren(empty);
}

// ใช้ labels ของ rows ที่ตอบจริง จึงยังระบุหลักสูตรถูกต้องเมื่อคำตอบมาจาก cache.
// ตรวจคู่ program/track: รองรับ 2–3 หลักสูตร และสองแผนของหลักสูตรเดียว.
function comparisonRows(rows) {
  if (![2, 3].includes(rows.length) || !rows.every(row => row && typeof row === "object"
    && typeof row.program === "string" && row.program.trim()
    && typeof row.track === "string" && row.track.trim()
    && (Object.hasOwn(row, "total_credits") || Object.hasOwn(row, "years")))) return null;
  return new Set(rows.map(row => `${row.program}/${row.track}`)).size === rows.length ? rows : null;
}

function appendMetric(row, key, label, unit) {
  if (!Object.hasOwn(row, key)) return;
  const value = row[key];
  if (value !== null && (typeof value !== "number" || !Number.isFinite(value))) return;
  const card = createElement("div", "answer-metric");
  card.append(createElement("p", "metric-label", label));
  const figure = createElement("p", "metric-figure");
  figure.append(createElement("strong", "metric-value", value === null ? "ไม่ระบุ" : numberFormat.format(value)));
  if (value !== null) figure.append(createElement("span", "metric-unit", unit));
  card.append(figure);
  answerHighlights.append(card);
}

function renderHighlights(rows) {
  answerHighlights.replaceChildren();
  answerHighlights.hidden = true;
  const targets = comparisonRows(rows);
  if (targets) {
    for (const row of targets) {
      const scope = `${row.program} · ${row.track}`;
      appendMetric(row, "total_credits", `${scope} — หน่วยกิตรวมหลักสูตร`, "หน่วยกิต");
      appendMetric(row, "years", `${scope} — ระยะเวลาหลักสูตร`, "ปี");
    }
    answerHighlights.hidden = answerHighlights.childElementCount === 0;
    return;
  }
  if (rows.length !== 1 || !rows[0] || typeof rows[0] !== "object") return;
  const row = rows[0];
  const partial = (row.missing_credit_slots || 0) > 0 || (row.incomplete_alt_slots || 0) > 0;
  const planned = row.year !== undefined && row.semester !== undefined;
  const metrics = [
    ["total_credits", partial ? "หน่วยกิตที่ระบุ" : row.year !== undefined ? "หน่วยกิตรวมในปีนี้" : "หน่วยกิตรวมหลักสูตร", "หน่วยกิต"],
    ["credits", partial ? "หน่วยกิตที่ระบุ" : planned ? "หน่วยกิตในเทอมนี้" : "หน่วยกิตรายวิชา", "หน่วยกิต"],
    ["years", "ระยะเวลาหลักสูตร", "ปี"],
    ["n_courses", planned ? "ช่องวิชาตามแผน" : "วิชาที่ตรงเงื่อนไข", planned ? "ช่อง" : "วิชา"],
    ["n_listed", "รายการรวมตัวเลือก", "รายการ"],
    ["n_slots", "ช่องวิชาที่ต้องเรียน", "ช่อง"]
  ];
  for (const [key, label, unit] of metrics) {
    appendMetric(row, key, label, unit);
  }
  answerHighlights.hidden = answerHighlights.childElementCount === 0;
}

function renderAnswer(text) {
  const content = document.createDocumentFragment();
  let block = null;
  let fields = null;
  let blockKind = null;
  let firstParagraph = true;
  for (const rawLine of text.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line) continue;
    if (/^รายการ\s+\d+$/.test(line)) {
      block = createElement("article", "answer-item");
      block.append(createElement("h3", "answer-item-title", line));
      fields = createElement("dl", "answer-fields");
      block.append(fields);
      blockKind = "item";
      content.append(block);
      continue;
    }
    if (/^ปี\s+\d+/.test(line)) {
      block = createElement("div", "answer-summary-block");
      fields = null;
      blockKind = "summary";
      content.append(block);
    }
    const isNotice = /^(?:หมายเหตุ:|ค้นคำเต็ม|ค้นข้อความย่อย|ค้นโดยข้าม|ผลนี้ตรง|แสดงช่วงคำอธิบาย|สรุปเฉพาะ|ผลที่ API|ข้อมูลหน่วยกิตไม่ครบ|ไม่พบรหัสวิชา)/.test(line);
    if (isNotice) {
      const note = createElement("p", "answer-note");
      appendAnswerText(note, line);
      const localNote = blockKind === "summary" && /^หมายเหตุ:/.test(line);
      (localNote ? block : content).append(note);
      if (!localNote) { block = null; fields = null; blockKind = null; }
      continue;
    }
    const field = line.match(/^([^:]{1,60}):\s*(.*)$/);
    if (blockKind === "item" && field) {
      fields.append(createElement("dt", "", field[1]));
      const value = createElement("dd");
      appendAnswerText(value, field[2]);
      fields.append(value);
    } else {
      const paragraph = createElement("p", firstParagraph && !block ? "answer-lead" : "answer-paragraph");
      if (field) {
        paragraph.append(createElement("strong", "answer-label", field[1] + ": "));
        appendAnswerText(paragraph, field[2]);
      } else {
        appendAnswerText(paragraph, line);
      }
      (block || content).append(paragraph);
      firstParagraph = false;
    }
  }
  if (text.length > 6000) {
    const full = createElement("details", "full-answer");
    full.append(createElement("summary", "", "อ่านคำตอบฉบับเต็มทุกส่วน"), content);
    answerBody.replaceChildren(createElement("p", "answer-lead", text.split(/\r?\n/)[0]), full);
  } else answerBody.replaceChildren(content);
}

function renderRows(rows, extraLabels = {}) {
  const container = document.getElementById("rows-table");
  container.replaceChildren();
  if (rows.length === 0) {
    container.append(createElement("p", "table-empty", "ไม่มีแถวข้อมูลสำหรับคำถามนี้"));
    return;
  }
  const columns = [...new Set(rows.flatMap((row) => Object.keys(row)))];
  const labels = {
    program: "หลักสูตร", track: "แผนการเรียน", difference: "อยู่เฉพาะแผน",
    root_code: "วิชาที่ถาม", depth: "ระดับในสายวิชาก่อน", terms: "ปี/เทอมตามแผน",
    requirements: "วิชาก่อนทั้งหมด", status: "ผลตรวจ", reason: "เหตุผล",
    code: "รหัสวิชา", name_th: "ชื่อภาษาไทย", name_en: "ชื่อภาษาอังกฤษ", degree: "ปริญญา",
    credits: "หน่วยกิต", total_credits: "หน่วยกิตรวม", years: "ระยะเวลา (ปี)",
    year: "ปี", semester: "เทอม", alt_group: "กลุ่มตัวเลือก", note: "หมายเหตุ",
    lecture_h: "ชั่วโมงบรรยาย", lab_h: "ชั่วโมงปฏิบัติ", self_h: "ชั่วโมงศึกษาด้วยตนเอง",
    description_th: "คำอธิบาย", course_name: "ชื่อวิชา", requires: "รหัสวิชาที่ต้องเรียน",
    required_name: "ชื่อวิชาที่ต้องเรียน", kind: "ประเภทเงื่อนไข", n_courses: "จำนวนวิชา / ช่องตามแผน",
    category: "หมวดวิชา", type: "ประเภทวิชา", source_code: "รหัสวิชาก่อน", source_name: "ชื่อวิชาก่อน",
    target_code: "รหัสตัวต่อ", target_name: "ชื่อวิชาตัวต่อ", requirements: "เงื่อนไขทั้งหมดที่บันทึก",
    n_listed: "รายการรวมตัวเลือก", n_slots: "ช่องที่ต้องเรียน", term_breakdown: "รายละเอียดรายเทอม",
    missing_credit_slots: "ช่องที่ไม่ระบุหน่วยกิต", incomplete_alt_slots: "ช่องที่ตัวเลือกมีข้อมูลไม่ครบ"
  };
  Object.assign(labels, extraLabels);
  const valueNode = (value) => {
    if (value === null || value === undefined) return createElement("span", "table-missing", "ไม่ระบุ");
    if (typeof value === "boolean") return createElement("span", "", value ? "ใช่" : "ไม่ใช่");
    if (typeof value !== "object") {
      const text = String(value);
      if (text.length < 250) return createElement("span", "", text);
      const details = createElement("details", "data-value");
      details.append(createElement("summary", "", "อ่านรายละเอียดทั้งหมด"), createElement("p", "", text));
      return details;
    }
    const details = createElement("details", "data-value");
    details.append(createElement("summary", "", Array.isArray(value) ? `${numberFormat.format(value.length)} รายการ` : "ดูรายละเอียด"));
    const list = createElement(Array.isArray(value) ? "ol" : "dl");
    for (const [key, item] of Object.entries(value)) {
      if (Array.isArray(value)) {
        const entry = createElement("li"); entry.append(valueNode(item)); list.append(entry);
      } else {
        const entry = createElement("dd"); entry.append(valueNode(item));
        list.append(createElement("dt", "", labels[key] || key), entry);
      }
    }
    details.append(list);
    return details;
  };
  const table = createElement("table", "result-table");
  table.append(createElement("caption", "visually-hidden", "ข้อมูลจากฐานข้อมูลที่ใช้ประกอบคำตอบ"));
  const head = createElement("thead");
  const headings = createElement("tr");
  columns.forEach((key) => {
    const header = createElement("th", "", labels[key] || key);
    header.scope = "col";
    headings.append(header);
  });
  head.append(headings);
  table.append(head);
  const body = createElement("tbody");
  const pageSize = 20;
  let page = 0;
  const pager = createElement("nav", "table-pager");
  pager.setAttribute("aria-label", "หน้าของรายการข้อมูล");
  const previous = createElement("button", "", "ก่อนหน้า"); previous.type = "button";
  const next = createElement("button", "", "ถัดไป"); next.type = "button";
  const status = createElement("span", ""); status.setAttribute("aria-live", "polite");
  const draw = () => {
    body.replaceChildren();
    const start = page * pageSize;
    rows.slice(start, start + pageSize).forEach((row) => {
    const record = createElement("tr");
    columns.forEach((key) => {
      let value = row[key];
      if (key === "difference") value = {coop_only: "มีเฉพาะ coop", nocoop_only: "มีเฉพาะ nocoop"}[value] || value;
      if (key === "requirements" && typeof value === "string") {
        try {
          const requirements = JSON.parse(value);
          if (Array.isArray(requirements)) {
            value = requirements.map((item) => `${item.code} ${item.name || "ไม่ระบุชื่อ"} (${item.kind === "pre" ? "บังคับก่อน" : "เรียนควบ"})`).join("; ");
          }
        } catch { /* ใช้ข้อความจาก API ตามเดิมเมื่อไม่ใช่ JSON; createElement ใส่เป็น text เท่านั้น. */ }
      }
      const cell = createElement("td"); cell.append(valueNode(value));
      record.append(cell);
    });
    body.append(record);
    });
    previous.disabled = page === 0;
    next.disabled = start + pageSize >= rows.length;
    status.textContent = `รายการ ${numberFormat.format(start + 1)}–${numberFormat.format(Math.min(start + pageSize, rows.length))} จาก ${numberFormat.format(rows.length)}`;
  };
  previous.addEventListener("click", () => { page -= 1; draw(); });
  next.addEventListener("click", () => { page += 1; draw(); });
  pager.append(previous, status, next);
  draw();
  table.append(body);
  container.append(table);
  if (rows.length > pageSize) container.prepend(pager);
  container.tabIndex = 0;
  container.setAttribute("role", "region");
  container.setAttribute("aria-label", "ตารางข้อมูลประกอบคำตอบ เลื่อนเพื่อดูคอลัมน์เพิ่มเติม");
}

const evidenceNames = {course: "ข้อมูลรายวิชา", plan_item: "แผนการเรียน", program: "ข้อมูลหลักสูตร",
  elective_slot: "บัญชีวิชาเลือก", prerequisite: "เงื่อนไขวิชาก่อน/วิชาควบ", unknown: "ข้อมูลประกอบ"};

function citationGroups(data) {
  const groups = new Map();
  for (const citation of Array.isArray(data.citations) ? data.citations : []) {
    if (!citation || !Array.isArray(citation.pages)) continue;
    const pages = citation.pages.filter(page => Number.isSafeInteger(page) && page > 0);
    if (!pages.length) continue;
    const fields = [citation.document_id, citation.source, citation.evidence_source, citation.page_basis,
      citation.program, citation.edition, citation.track,
      citation.course_code, citation.year, citation.semester];
    const key = JSON.stringify(fields);
    if (!groups.has(key)) groups.set(key, {citation, references: new Map()});
    const group = groups.get(key);
    for (const page of pages) {
      const reference = citation.page_references?.find(item => item.stored_page === page)
        || {stored_page: page, page_basis: "unknown", verification_status: "unknown"};
      group.references.set(JSON.stringify([page, reference.pdf_page, reference.printed_page, reference.section_name]), reference);
    }
  }
  return [...groups.values()].map(group => ({citation: group.citation,
    references: [...group.references.values()].sort((a, b) => a.stored_page - b.stored_page)}));
}

function citationPdfUrl(citation, reference) {
  if (!Number.isSafeInteger(reference.pdf_page) || reference.pdf_page < 1 || typeof reference.pdf_url !== "string") return null;
  try {
    const url = new URL(reference.pdf_url, location.origin);
    return url.origin === location.origin && /^\/api\/documents\/doc-[a-f0-9]{16}$/.test(url.pathname)
      && url.pathname === `/api/documents/${citation.document_id}` && !url.search && !url.username && !url.password
      && url.hash === `#page=${reference.pdf_page}` ? url.href : null;
  } catch { return null; }
}

function citationText(value) {
  if (typeof value !== "string") return null;
  const text = value.trim();
  return text && !["ยังไม่ระบุ", "ไม่ระบุ", "ไม่ระบุปี", "unknown"].includes(text) ? text : null;
}

function citationPageText(reference) {
  const pdf = Number.isSafeInteger(reference.pdf_page) && reference.pdf_page > 0;
  const printed = citationText(reference.printed_page);
  const parts = [pdf ? `หน้า PDF ${reference.pdf_page}` : `เลขหน้าที่บันทึกไว้ ${reference.stored_page}`];
  if (printed) parts.push(`เลขหน้าในเล่ม ${printed}`);
  if (pdf && reference.stored_page !== reference.pdf_page) parts.push(`เลขหน้าเดิมในข้อมูล ${reference.stored_page}`);
  const section = citationText(reference.section_name);
  if (section) parts.push(`หัวข้อ: ${section}`);
  return parts.join(" · ");
}

function renderCitations(data) {
  citationsList.replaceChildren();
  const groups = citationGroups(data);
  let more = null;
  groups.forEach(({citation, references}, index) => {
    const card = createElement("article", "citation-card");
    card.id = /^ref-[a-f0-9]{16}$/.test(citation.citation_id || "") ? citation.citation_id : `citation-${index + 1}`;
    const actual = data.scope?.targets?.length === 1 ? data.scope.targets[0] : null;
    const scope = [citation.program || actual?.program,
      citation.edition_label || data.edition_label, trackLabel(citation.track || actual?.track)];
    if (typeof citation.course_code === "string") scope.push(`วิชา ${citation.course_code}`);
    if (Number.isInteger(citation.year)) scope.push(`ปี ${citation.year}`);
    if (Number.isInteger(citation.semester)) scope.push(`เทอม ${citation.semester}`);
    const heading = createElement("div", "citation-heading");
    heading.append(createElement("h4", "citation-title", `[${index + 1}] ${evidenceNames[citation.evidence_source] || evidenceNames.unknown}`));
    const verified = references.every(reference => reference.verification_status === "content_verified");
    const badge = createElement("span", "citation-status", verified ? "ตรวจเนื้อหาแล้ว" : "อ้างจากข้อมูลที่สกัด");
    badge.dataset.verified = String(verified);
    heading.append(badge);
    card.append(heading);
    const title = citationText(citation.document_title);
    if (title) card.append(createElement("p", "citation-document", title));
    const scopeText = scope.map(citationText).filter(Boolean).join(" · ");
    if (scopeText) card.append(createElement("p", "citation-scope", scopeText));
    const supports = (Array.isArray(citation.supports) ? citation.supports : []).map(citationText).filter(Boolean);
    if (supports.length) card.append(createElement("p", "citation-supports", `ใช้ประกอบ: ${supports.join("; ")}`));
    if (citation.source === "study_plan" && citation.evidence_source === "course") {
      card.append(createElement("p", "citation-note", "เลขหน้านี้มาจากข้อมูลรายวิชา ไม่ใช่หน้าแผนการเรียน"));
    }
    const pageList = createElement("ul", "citation-page-list");
    references.forEach(reference => {
      const item = createElement("li", "citation-page-row");
      item.append(createElement("span", "", citationPageText(reference)));
      const url = citationPdfUrl(citation, reference);
      if (url) {
        const link = createElement("a", "citation-open", `เปิด PDF หน้า ${reference.pdf_page}`);
        link.href = url;
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        link.setAttribute("aria-label", `เปิด PDF หน้า ${reference.pdf_page} ของ ${citation.document_title || "เอกสารอ้างอิง"} ในแท็บใหม่`);
        item.append(link);
      }
      pageList.append(item);
    });
    card.append(pageList);
    const section = citationText(citation.section_name);
    if (section) card.append(createElement("p", "citation-section", `หัวข้อในเอกสาร: ${section}`));
    if (index >= 6 && more === null) {
      more = createElement("details", "citations-more");
      more.append(createElement("summary", "", `ดูหลักฐานเพิ่มเติมอีก ${groups.length - 6} รายการ`));
      citationsList.append(more);
    }
    (index >= 6 ? more : citationsList).append(card);
  });
  answerCitations.hidden = groups.length === 0 && data.rows.length === 0 && data.sql.trim() === "";
  document.getElementById("citations-description").textContent = groups.length
    ? "หน้า PDF นับจากหน้าแรกของไฟล์ รวมปกและคำนำที่มี ส่วนเลขหน้าในเล่มคือเลขที่พิมพ์บนกระดาษ ไฟล์เฉพาะส่วนอาจมีเลขหน้า PDF ต่างจากเลขหน้าเดิมในข้อมูล สถานะข้อมูลที่สกัดยังไม่ใช่การตรวจเนื้อหา PDF"
    : "ข้อมูลคำตอบนี้ยังไม่มีเลขหน้าอ้างอิงที่บันทึกไว้";
}

function renderTiming(elapsedMs, serverMs) {
  // เวลาผู้ใช้รอรวม fetch, อ่าน JSON และแสดงคำตอบ; แยกจากเวลาประมวลผลฝั่ง API.
  const formatMs = value => value < 1000 ? `${Math.round(value)} มิลลิวินาที`
    : `${(value / 1000).toLocaleString("th-TH", {minimumFractionDigits: 2, maximumFractionDigits: 2})} วินาที`;
  responseTime.textContent = `เวลาที่รอ ${formatMs(elapsedMs)}`;
  answerTiming.hidden = false;
  const hasServerTime = typeof serverMs === "number" && Number.isFinite(serverMs) && serverMs >= 0;
  processingTime.hidden = !hasServerTime;
  processingTime.textContent = hasServerTime ? `ประมวลผล ${formatMs(serverMs)}` : "";
}

function renderAnalysis(analysis) {
  answerAnalysis.replaceChildren();
  answerAnalysis.hidden = !analysis;
  if (!analysis) return;
  const labels = {data_query: "ผลตรวจข้อมูลและความครบถ้วน", student_check: "ผลตรวจเบื้องต้น", study_draft: "ร่างแผนภายใต้ข้อสมมติ",
    prerequisite_graph: "ความสัมพันธ์วิชาก่อนที่บันทึกไว้", dependent_terms: "ตัวต่อพร้อมปี/เทอม",
    conditional_prerequisites: "เงื่อนไขเมื่อยังไม่ผ่านวิชา"};
  answerAnalysis.append(createElement("h3", "", labels[analysis.kind] || "ข้อมูลประกอบ"));
  if (analysis.kind === "data_query") {
    answerAnalysis.append(createElement("p", "", analysis.complete
      ? `คำนวณจากข้อมูลครบตามเงื่อนไข · ส่งผล ${numberFormat.format(analysis.total_rows)} แถว โดยอ่านรายการได้ทุกหน้าของตาราง`
      : "ข้อมูลผลลัพธ์ยังไม่ครบตามเงื่อนไข"));
    if (analysis.evidence_status === "no_stored_pages") answerAnalysis.append(createElement("p", "", "ฐานข้อมูลไม่ได้บันทึกหน้าอ้างอิงสำหรับผลนี้"));
  }
  for (const [key, title] of [["assumptions", "ข้อสมมติ"], ["missing_data", "ข้อมูลที่ยังขาด"], ["limitations", "ข้อจำกัดของข้อมูลที่ใช้ตอบ"]]) {
    if (!Array.isArray(analysis[key]) || !analysis[key].length) continue;
    answerAnalysis.append(createElement("strong", "", title));
    const list = createElement("ul");
    for (const value of analysis[key]) list.append(createElement("li", "", value));
    answerAnalysis.append(list);
  }
  if (Array.isArray(analysis.unresolved) && analysis.unresolved.length) {
    answerAnalysis.append(createElement("strong", "", "รายการที่ยังจัดไม่ลง/ต้องตรวจข้อมูล"));
    const list = createElement("ul");
    for (const item of analysis.unresolved) list.append(createElement("li", "", `${item.code}: ${item.reason}`));
    answerAnalysis.append(list);
  }
  if (Array.isArray(analysis.elective_slots) && analysis.elective_slots.length) {
    answerAnalysis.append(createElement("strong", "", "ช่องที่ต้องเลือกวิชาจริงหรือข้อมูลยังไม่ครบ"));
    const list = createElement("ul");
    for (const item of analysis.elective_slots) list.append(createElement("li", "", `แผนเดิม ${item.year}/${item.semester}: ${item.codes.join(" / ")} (${item.credits ?? "ไม่ทราบ"} หน่วยกิต)`));
    answerAnalysis.append(list);
  }
}

function renderPagination(data) {
  document.getElementById("result-pagination")?.remove();
  if (!lastAskPayload || !Number.isInteger(data.page) || (!data.has_more && data.page <= 1)) return;
  const controls = createElement("div", "pagination-controls");
  controls.id = "result-pagination";
  controls.setAttribute("aria-label", "หน้ารายการผลค้น");
  for (const [label, page, disabled] of [["หน้าก่อน", data.page - 1, data.page <= 1], ["หน้าถัดไป", data.page + 1, !data.has_more]]) {
    const button = createElement("button", "button-secondary", label);
    button.type = "button";
    button.disabled = disabled;
    button.addEventListener("click", async () => {
      if (uiState === "loading") return;
      const payload = { ...lastAskPayload, page };
      setState("loading", "กำลังอ่านรายการ…");
      try {
        const response = await fetch("/api/ask", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
        const next = await response.json();
        if (!response.ok || typeof next?.answer !== "string" || !Array.isArray(next?.rows)) throw new Error(typeof next?.detail === "string" ? next.detail : "อ่านหน้าผลค้นไม่สำเร็จ");
        renderResponse(next);
        setState("success", "ตอบคำถามสำเร็จ");
      } catch (error) { setState("error", error.message || "อ่านหน้าผลค้นไม่สำเร็จ"); }
    });
    controls.append(button);
  }
  document.getElementById("rows-table").append(controls);
}

function renderResponse(data) {
  lastResponse = data;
  copyButton.disabled = false;
  copyButton.textContent = "คัดลอกคำตอบ";
  answerContext.hidden = false;
  // summary มาจากชุดรหัสเต็ม จึงระบุสองแผนได้แม้ rows ว่าง/ถูกจำกัด/มาจาก cache.
  const diff = data.comparison && typeof data.comparison.program === "string"
    && Array.isArray(data.comparison.tracks) && data.comparison.tracks.length === 2
    && data.comparison.tracks.includes("coop") && data.comparison.tracks.includes("nocoop")
    ? data.comparison : null;
  const targets = Array.isArray(data.analysis?.targets) && data.analysis.targets.length
    ? data.analysis.targets : comparisonRows(data.rows);
  const actual = data.scope?.targets?.[0];
  document.getElementById("answer-program").textContent = diff ? diff.program : targets
    ? targets.map(row => row.program).join(" ↔ ") : actual?.program || lastAskPayload?.program || programSelect.value;
  document.getElementById("answer-edition").textContent = data.edition_label || "ไม่ระบุปี";
  document.getElementById("answer-track").textContent = diff ? diff.tracks.map(trackLabel).join(" ↔ ") : targets
    ? new Set(targets.map(row => row.track)).size === 1 ? trackLabel(targets[0].track)
      : targets.map(row => `${row.program}: ${trackLabel(row.track)}`).join(" · ")
    : trackLabel(actual?.track || lastAskPayload?.track || trackSelect.value);
  answerIntro.textContent = diff ? "ส่วนต่างรหัสรายวิชาในแผนทั้งสองของหลักสูตรเดียวกัน"
    : targets
    ? "เปรียบเทียบข้อมูลจากหลักสูตรและแผนการเรียนที่ใช้ตอบจริง"
    : "ข้อมูลจากหลักสูตร ฉบับ และแผนที่ใช้ตอบ";
  document.getElementById("answer-question").textContent = typeof data.question === "string" ? data.question : question.value.trim();
  renderHighlights(data.rows);
  renderAnswer(data.answer);
  renderRows(data.rows, data.analysis?.labels || {});
  renderAnalysis(data.analysis);
  renderCitations(data);
  document.getElementById("row-count").textContent = Number.isInteger(data.total_count)
    ? `แสดง ${numberFormat.format(data.rows.length)} จากทั้งหมด ${numberFormat.format(data.total_count)} รายการ`
    : `${numberFormat.format(data.rows.length)} แถว`;
  renderPagination(data);
  document.getElementById("rows").textContent = JSON.stringify(data.rows, null, 2);
  document.getElementById("sql").textContent = data.sql;
  responseDetails.hidden = data.rows.length === 0 && data.sql.trim() === "";
}

function formatAnswerForCopy(data) {
  // สร้างจาก response เต็ม ไม่อ่านแค่ DOM/หน้าตารางที่กำลังเปิด และคงฉบับของคำตอบ.
  const targets = data.scope?.targets || [];
  const context = targets.map(target => [target.program,
    target.edition_label || data.edition_label, trackLabel(target.track)].filter(Boolean).join(" · "));
  const parts = [`คำถาม: ${data.question}`, context.join("\n"), data.answer];
  if (data.rows?.length) {
    const columns = [...new Set(data.rows.flatMap(row => Object.keys(row)))];
    const labels = {code: "รหัสวิชา", name_th: "ชื่อภาษาไทย", name_en: "ชื่อภาษาอังกฤษ",
      credits: "หน่วยกิต", program: "หลักสูตร", track: "แผน", year: "ชั้นปี", semester: "เทอม", pages: "เลขหน้าที่แนบกับข้อมูล"};
    const text = value => (value == null ? "ไม่ระบุ" : typeof value === "object"
      ? JSON.stringify(value) : String(value)).replace(/[\t\r\n]+/g, " ");
    parts.push(`ข้อมูลประกอบ (${data.rows.length} แถวที่ API คืน):`,
      [columns.map(key => data.analysis?.labels?.[key] || labels[key] || key).join("\t"),
        ...data.rows.map(row => columns.map(key => text(row[key])).join("\t"))].join("\n"));
  }
  for (const key of ["assumptions", "missing_data", "limitations", "unresolved", "elective_slots"]) {
    const values = data.analysis?.[key];
    if (Array.isArray(values) && values.length) {
      const titles = {assumptions: "ข้อสมมติ", missing_data: "ข้อมูลที่ขาด", limitations: "ข้อจำกัด",
        unresolved: "รายการที่ยังจัดไม่ได้", elective_slots: "ช่องวิชาเลือก"};
      parts.push(`${titles[key]}:`, ...values.map(value => typeof value === "string" ? value : JSON.stringify(value)));
    }
  }
  const groups = citationGroups(data);
  parts.push(groups.length ? "แหล่งอ้างอิง:" : "ยังไม่มีเลขหน้าอ้างอิงที่บันทึกไว้");
  groups.forEach(({citation, references}, index) => {
    parts.push([`[${index + 1}] ${evidenceNames[citation.evidence_source] || evidenceNames.unknown}`,
      citationText(citation.document_title), citation.program, citationText(citation.edition_label || data.edition_label),
      trackLabel(citation.track), citation.course_code && `วิชา ${citation.course_code}`,
      citation.year && `ปี ${citation.year}`, citation.semester && `เทอม ${citation.semester}`].filter(Boolean).join(" · "));
    const supports = (Array.isArray(citation.supports) ? citation.supports : []).map(citationText).filter(Boolean);
    if (supports.length) parts.push(`ใช้ประกอบ: ${supports.join("; ")}`);
    for (const reference of references) {
      parts.push(citationPageText(reference));
      const url = citationPdfUrl(citation, reference);
      if (url) parts.push(url);
    }
    parts.push(references.every(reference => reference.verification_status === "content_verified")
      ? "สถานะ: ตรวจเนื้อหาแล้ว" : "สถานะ: อ้างจากข้อมูลที่สกัด");
    if (citation.source === "study_plan" && citation.evidence_source === "course") parts.push("เลขหน้านี้มาจากข้อมูลรายวิชา ไม่ใช่หน้าแผนการเรียน");
  });
  return parts.filter(Boolean).join("\n\n");
}

copyButton.addEventListener("click", async () => {
  const data = lastResponse;
  if (!data) return;
  const text = formatAnswerForCopy(data);
  copyButton.disabled = true;
  try {
    if (!navigator.clipboard?.writeText) throw new Error("Clipboard unavailable");
    await navigator.clipboard.writeText(text);
    if (lastResponse !== data) return;
    copyFallback.hidden = true;
    copyButton.textContent = "คัดลอกแล้ว ✓";
    statusMessage.textContent = "คัดลอกคำตอบพร้อมฉบับหลักสูตรและแหล่งอ้างอิงแล้ว";
  } catch {
    if (lastResponse !== data) return;
    copyButton.textContent = "คัดลอกด้วยตนเอง";
    const field = copyFallback.querySelector("textarea");
    field.value = text;
    copyFallback.hidden = false;
    field.focus(); field.select();
    statusMessage.textContent = "เลือกข้อความคำตอบไว้แล้ว สามารถคัดลอกด้วย Ctrl+C หรือเมนูของอุปกรณ์";
  } finally {
    if (lastResponse === data) copyButton.disabled = false;
  }
});

// จุดเดียวสำหรับเปลี่ยนสถานะและควบคุม input ทั้งหมด
function setState(state, message) {
  uiState = state;
  statusMessage.dataset.state = state;
  statusMessage.textContent = message;
  const loading = state === "loading";
  const ready = programs.length > 0 && editionSelect.options.length > 0 && trackSelect.options.length > 0;
  form.setAttribute("aria-busy", String(loading));
  question.disabled = loading;
  programSelect.disabled = loading || programs.length === 0;
  editionSelect.disabled = loading || editionSelect.options.length === 0;
  trackSelect.disabled = loading || !ready;
  submitButton.disabled = loading || !ready;
  submitButton.textContent = loading ? "กำลังโหลด…" : "ถาม";
  answerPanel.dataset.state = state;
  answerPanel.setAttribute("aria-busy", String(loading));
  answerBadge.textContent = {
    idle: "รอคำถาม", loading: "กำลังค้นหา", success: "แสดงคำตอบแล้ว", error: "ค้นหาไม่สำเร็จ"
  }[state];
  if (state !== "success") {
    resetResult();
    renderEmptyResult(state, message);
  }
}

function editionsFor(program) {
  // client รองรับ response เดิมด้วย; ตัวเลือกจริงทั้งหมดมาจาก API.
  return program?.editions || [{edition: "default", label: "ไม่ระบุปี", tracks: program?.tracks || []}];
}

function updateEditions() {
  const selected = programs.find(item => item.program === programSelect.value);
  const previous = editionSelect.value;
  const editions = editionsFor(selected);
  editionSelect.replaceChildren(...editions.map(item => {
    const option = document.createElement("option");
    option.value = item.edition;
    option.textContent = item.label;
    return option;
  }));
  editionSelect.value = editions.some(item => item.edition === previous)
    ? previous : selected?.default_edition || editions[0]?.edition || "";
  updateTracks();
}

function updateTracks() {
  const selected = programs.find(
    (item) => item.program === programSelect.value
  );

  const previous = trackSelect.value;
  const edition = editionsFor(selected).find(item => item.edition === editionSelect.value);
  trackSelect.replaceChildren(
    ...(edition?.tracks || []).map((track) => {
      const option = document.createElement("option");
      option.value = track;
      option.textContent = trackLabel(track);
      return option;
    })
  );
  if (edition?.tracks.includes(previous)) trackSelect.value = previous;
}

async function loadPrograms() {
  setState("loading", "กำลังโหลดตัวเลือกหลักสูตร…");

  try {
    const response = await fetch("/api/curricula");

    if (!response.ok) {
      throw new Error(`โหลดหลักสูตรไม่ได้ (HTTP ${response.status})`);
    }

    const data = await response.json();

    if (!Array.isArray(data.programs) || data.programs.length === 0) {
      throw new Error("ไม่พบหลักสูตรในระบบ");
    }

    programs = data.programs;

    programSelect.replaceChildren(
      ...programs.map((item) => {
        const option = document.createElement("option");
        option.value = item.program;
        option.textContent = item.program;
        return option;
      })
    );

    updateEditions();
    if (trackSelect.options.length === 0) {
      throw new Error("ไม่พบแผนการเรียนของหลักสูตรนี้");
    }
    setState("idle", "พร้อมรับคำถาม — เลือกหลักสูตรและพิมพ์คำถาม");
  } catch (error) {
    setState("error", `โหลดตัวเลือกไม่สำเร็จ: ${error.message} กรุณารีเฟรชหน้าเว็บ`);
  }
}

programSelect.addEventListener("change", () => {
  updateEditions();
  setState("idle", "พร้อมรับคำถาม");
});
editionSelect.addEventListener("change", () => {
  updateTracks();
  setState("idle", "พร้อมรับคำถาม");
});
trackSelect.addEventListener("change", () => setState("idle", "พร้อมรับคำถาม"));
question.addEventListener("input", () => {
  if (uiState !== "loading") setState("idle", "พร้อมรับคำถาม");
});
loadPrograms();

form.addEventListener("submit", async (event) => {
  event.preventDefault();

  const form = event.currentTarget;
  const button = form.querySelector('button[type="submit"]');

  if (button.disabled) return;

  if (question.value.trim().length < 2) {
    setState("error", "กรุณาพิมพ์คำถามอย่างน้อย 2 ตัวอักษร");
    return;
  }
  setState("loading", "กำลังค้นข้อมูลและสร้างคำตอบ กรุณารอสักครู่…");
  const started = performance.now();
  let serverMs;
  try {
    const response = await fetch("/api/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(lastAskPayload = {
        question: question.value.trim(),
        program: programSelect.value,
        edition: editionSelect.value,
        track: trackSelect.value,
        page: 1,
        page_size: 20
      })
    });

    const data = await response.json().catch(() => null);
    if (!response.ok) {
      console.error(
        "POST /api/ask ไม่สำเร็จ:",
        response.status,
        JSON.stringify(data, null, 2)
      );
    }

    if (!response.ok) {
      let message = `เกิดข้อผิดพลาด (HTTP ${response.status})`;

      if (Array.isArray(data?.detail)) {
        // FastAPI ส่ง validation error เป็นรายการ
        message = data.detail.map((item) => {
          const field = (item.loc || [])
            .filter((part) => part !== "body")
            .join(".");

          return `${field || "ข้อมูล"}: ${item.msg || "ไม่ถูกต้อง"}`;
        }).join("\n");
      } else if (typeof data?.detail === "string") {
        message = data.detail;
      }

      throw new Error(message);
    }

    if (typeof data?.answer !== "string" || !Array.isArray(data?.rows) || typeof data?.sql !== "string") {
      throw new Error("เซิร์ฟเวอร์ส่งคำตอบในรูปแบบที่อ่านไม่ได้");
    }

    renderResponse(data);
    serverMs = data.processing_ms;
    setState("success", "ตอบคำถามสำเร็จ");
    if (window.matchMedia("(max-width: 767px)").matches) {
      answerPanel.scrollIntoView({
        behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth",
        block: "start"
      });
    }
  } catch (error) {
    setState("error", error instanceof TypeError
      ? "ติดต่อเซิร์ฟเวอร์ไม่ได้ กรุณากดถามเพื่อลองใหม่"
      : `ผิดพลาด: ${error.message}`);
  } finally {
    // แสดงเวลาของครั้งปัจจุบันทั้งสำเร็จและผิดพลาด; ค่าเดิมถูกล้างเมื่อเริ่มคำถามใหม่.
    renderTiming(performance.now() - started, serverMs);
  }
});
