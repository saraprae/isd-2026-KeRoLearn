const programSelect = document.getElementById("program");
const trackSelect = document.getElementById("track");
const submitButton = document.querySelector(
  '#ask-form button[type="submit"]'
);

let programs = [];
let uiState = "idle";
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
const numberFormat = new Intl.NumberFormat("th-TH", { maximumFractionDigits: 20 });

function createElement(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
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
// จำกัดรูปแบบให้เป็นสองหลักสูตรและ metadata ที่รองรับ ไม่ตีความรายการวิชาทั่วไปเป็นการเทียบ.
function comparisonRows(rows) {
  if (rows.length !== 2 || !rows.every(row => row && typeof row === "object"
    && typeof row.program === "string" && row.program.trim()
    && typeof row.track === "string" && row.track.trim()
    && (Object.hasOwn(row, "total_credits") || Object.hasOwn(row, "years")))) return null;
  return new Set(rows.map(row => row.program)).size === 2 ? rows : null;
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
  answerBody.replaceChildren(content);
}

function renderRows(rows) {
  const container = document.getElementById("rows-table");
  container.replaceChildren();
  if (rows.length === 0) {
    container.append(createElement("p", "table-empty", "ไม่มีแถวข้อมูลสำหรับคำถามนี้"));
    return;
  }
  const columns = [...new Set(rows.flatMap((row) => Object.keys(row)))];
  const labels = {
    program: "หลักสูตร", track: "แผนการเรียน",
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
  rows.forEach((row) => {
    const record = createElement("tr");
    columns.forEach((key) => {
      let value = row[key];
      if (key === "requirements" && typeof value === "string") {
        try {
          const requirements = JSON.parse(value);
          if (Array.isArray(requirements)) {
            value = requirements.map((item) => `${item.code} ${item.name || "ไม่ระบุชื่อ"} (${item.kind === "pre" ? "บังคับก่อน" : "เรียนควบ"})`).join("; ");
          }
        } catch { /* ใช้ข้อความจาก API ตามเดิมเมื่อไม่ใช่ JSON; createElement ใส่เป็น text เท่านั้น. */ }
      }
      const cell = createElement("td", value === null || value === undefined ? "table-missing" : "",
        value === null || value === undefined ? "ไม่ระบุ" : typeof value === "object" ? JSON.stringify(value) : String(value));
      record.append(cell);
    });
    body.append(record);
  });
  table.append(body);
  container.append(table);
  container.tabIndex = 0;
  container.setAttribute("role", "region");
  container.setAttribute("aria-label", "ตารางข้อมูลประกอบคำตอบ เลื่อนเพื่อดูคอลัมน์เพิ่มเติม");
}

function renderCitations(data) {
  // pages เป็นหน้าที่บันทึกกับข้อมูลใน DB; ไม่สร้างลิงก์ PDF หรือเดาเลขหน้า.
  const sources = {course: "ข้อมูลรายวิชา", study_plan: "แผนการเรียน",
    program: "ข้อมูลหลักสูตร", prerequisite: "เงื่อนไขวิชาก่อน/วิชาควบ"};
  citationsList.replaceChildren();
  const groups = new Map();
  for (const citation of Array.isArray(data.citations) ? data.citations : []) {
    if (!citation || !Array.isArray(citation.pages) || !Object.hasOwn(sources, citation.source)) continue;
    const pages = citation.pages.filter(page => Number.isSafeInteger(page) && page > 0);
    if (!pages.length) continue;
    // รวมหน้าซ้ำที่มาจากขอบเขตเดียวกัน แม้ API ส่ง citation กลุ่มเดิมมากกว่าครั้งเดียว.
    const fields = [citation.source, citation.program, citation.track,
      citation.course_code, citation.year, citation.semester];
    const key = JSON.stringify(fields);
    if (!groups.has(key)) groups.set(key, {citation, pages: new Set()});
    pages.forEach(page => groups.get(key).pages.add(page));
  }
  for (const {citation, pages} of groups.values()) {
    const card = createElement("article", "citation-card");
    const scope = [citation.program || programSelect.value, citation.track || trackSelect.value];
    if (typeof citation.course_code === "string") scope.push(`วิชา ${citation.course_code}`);
    if (Number.isInteger(citation.year)) scope.push(`ปี ${citation.year}`);
    if (Number.isInteger(citation.semester)) scope.push(`เทอม ${citation.semester}`);
    card.append(createElement("p", "citation-title", sources[citation.source]));
    card.append(createElement("p", "citation-scope", scope.filter(Boolean).join(" · ")));
    const pageList = createElement("div", "citation-pages");
    [...pages].sort((a, b) => a - b).forEach(page => {
      pageList.append(createElement("span", "citation-page", `หน้า ${page}`));
    });
    card.append(pageList);
    citationsList.append(card);
  }
  answerCitations.hidden = groups.size === 0 && data.rows.length === 0 && data.sql.trim() === "";
  document.getElementById("citations-description").textContent = groups.size
    ? "เลขหน้าที่พบข้อมูลในหนังสือหลักสูตร ตามข้อมูลที่บันทึกไว้ในฐานข้อมูล"
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

function renderResponse(data) {
  answerContext.hidden = false;
  const targets = comparisonRows(data.rows);
  document.getElementById("answer-program").textContent = targets
    ? targets.map(row => row.program).join(" ↔ ") : programSelect.value;
  document.getElementById("answer-track").textContent = targets
    ? new Set(targets.map(row => row.track)).size === 1 ? targets[0].track
      : targets.map(row => `${row.program}: ${row.track}`).join(" · ")
    : trackSelect.value;
  answerIntro.textContent = targets
    ? "เปรียบเทียบข้อมูลจากหลักสูตรและแผนการเรียนที่ใช้ตอบจริง"
    : "ข้อมูลสำหรับหลักสูตรและแผนการเรียนที่คุณเลือก";
  document.getElementById("answer-question").textContent = typeof data.question === "string" ? data.question : question.value.trim();
  renderHighlights(data.rows);
  renderAnswer(data.answer);
  renderRows(data.rows);
  renderCitations(data);
  document.getElementById("row-count").textContent = `${numberFormat.format(data.rows.length)} แถว`;
  document.getElementById("rows").textContent = JSON.stringify(data.rows, null, 2);
  document.getElementById("sql").textContent = data.sql;
  responseDetails.hidden = data.rows.length === 0 && data.sql.trim() === "";
}

// จุดเดียวสำหรับเปลี่ยนสถานะและควบคุม input ทั้งหมด
function setState(state, message) {
  uiState = state;
  statusMessage.dataset.state = state;
  statusMessage.textContent = message;
  const loading = state === "loading";
  const ready = programs.length > 0 && trackSelect.options.length > 0;
  form.setAttribute("aria-busy", String(loading));
  question.disabled = loading;
  programSelect.disabled = loading || programs.length === 0;
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

function updateTracks() {
  const selected = programs.find(
    (item) => item.program === programSelect.value
  );

  trackSelect.replaceChildren(
    ...(selected?.tracks || []).map((track) => {
      const option = document.createElement("option");
      option.value = track;
      option.textContent = track;
      return option;
    })
  );


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

    updateTracks();
    if (trackSelect.options.length === 0) {
      throw new Error("ไม่พบแผนการเรียนของหลักสูตรนี้");
    }
    setState("idle", "พร้อมรับคำถาม — เลือกหลักสูตรและพิมพ์คำถาม");
  } catch (error) {
    setState("error", `โหลดตัวเลือกไม่สำเร็จ: ${error.message} กรุณารีเฟรชหน้าเว็บ`);
  }
}

programSelect.addEventListener("change", () => {
  updateTracks();
  setState("idle", "พร้อมรับคำถาม");
});
trackSelect.addEventListener("change", () => setState("idle", "พร้อมรับคำถาม"));
question.addEventListener("input", () => {
  if (uiState !== "loading") setState("idle", "พร้อมรับคำถาม");
});
loadPrograms();

  document.getElementById("ask-form").addEventListener("submit", async (event) => {
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
      body: JSON.stringify({
        question: document.getElementById("question").value.trim(),
        program: programSelect.value,
        track: trackSelect.value
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
