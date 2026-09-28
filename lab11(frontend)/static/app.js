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
  if (state !== "success") {
    document.getElementById("answer").textContent =
      state === "idle" ? "รอคำถาม..." : message;
    document.getElementById("rows").textContent = "-";
    document.getElementById("sql").textContent = "-";
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
  const answer = document.getElementById("answer");
  const rows = document.getElementById("rows");
  const sql = document.getElementById("sql");

  if (button.disabled) return;

  if (question.value.trim().length < 2) {
    setState("error", "กรุณาพิมพ์คำถามอย่างน้อย 2 ตัวอักษร");
    return;
  }
  setState("loading", "กำลังค้นข้อมูลและสร้างคำตอบ กรุณารอสักครู่…");

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

    answer.textContent = data.answer;
    rows.textContent = JSON.stringify(data.rows, null, 2);
    sql.textContent = data.sql;
    setState("success", "ตอบคำถามสำเร็จ");
  } catch (error) {
    setState("error", error instanceof TypeError
      ? "ติดต่อเซิร์ฟเวอร์ไม่ได้ กรุณากดถามเพื่อลองใหม่"
      : `ผิดพลาด: ${error.message}`);
  }
});
