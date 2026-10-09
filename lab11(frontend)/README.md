# Clearwave frontend

FastAPI serves `static/index.html`, `static/app.js`, and the compiled `static/style.css`.
The answer panel presents numeric summaries, readable course cards, and highlighted notes.
Database rows appear in a table inside a disclosure; raw JSON and SQL remain available in nested disclosures.
Two-program comparisons show the actual programs and tracks from returned rows, with per-program credit/duration cards and Thai table headings.

## Edit styles

Edit `styles/tailwind.css`. It uses Tailwind CSS v4 `@apply` with the existing selectors.
SVG waves and icons are decorative CSS pseudo-elements, so they add no DOM nodes.
Fonts use the local sans-serif stack; no external font or runtime CDN is required.

From this directory:

```sh
npm ci
npm run build:css
```

For ongoing CSS edits, run `npm run watch:css`.
Commit the compiled `static/style.css` so Python can serve it without Node.js at runtime.

Run the existing FastAPI command from the repository root, then open http://127.0.0.1:8000/.

The form uses two columns at 640px and the form/answer workspace uses two columns at 768px. It retains all four UI states,
and respects reduced-motion preferences.

The answer is rendered with text nodes rather than HTML from the API. Numeric highlights use the returned rows without adding totals, and missing credits retain the backend's notes. Loading, errors, and edits clear previous results, citations and timing. The request and four core response fields are preserved; optional `citations` and `processing_ms` are now displayed.

See the [combined Lab 10 / Lab 11 handoff](../lab10_fastapi/curriculum_app/HANDOFF.md) for the implementation, function comparison, workflow, data limitations, metrics, verification results and cleanup manifest. The header shows browser wait time and API processing time separately. The source section shows recorded book pages without inventing PDF links; responses without page metadata show an explicit missing-reference message.

Tailwind reference: https://tailwindcss.com/docs/functions-and-directives

## API Contract — Frontend กับ Backend

Contract นี้ครอบคลุม 2 endpoints ที่ `static/app.js` เรียกใช้จริง โดยอ้างอิง
[`main.py`](../lab10_fastapi/curriculum_app/main.py),
[`schemas.py`](../lab10_fastapi/curriculum_app/schemas.py) และ
[`config.py`](../lab10_fastapi/curriculum_app/config.py)

### ข้อตกลงร่วม

- Base URL สำหรับการรันในเครื่อง: `http://127.0.0.1:8000`
- FastAPI เสิร์ฟหน้าเว็บและ API จาก origin เดียวกัน จึงใช้ URL แบบ `/api/...` ใน `fetch()`
- รับและส่งข้อมูลเป็น JSON; `POST /api/ask` ต้องส่ง `Content-Type: application/json`
- สอง endpoints นี้ยังไม่มีการตรวจ API key หรือการยืนยันตัวตนในโค้ดปัจจุบัน
- API อื่นของ Backend ดูได้ที่ `/docs` หรือ `/openapi.json` เมื่อเปิดเซิร์ฟเวอร์

### 1. GET /api/curricula

**หน้าที่:** ส่งรายการหลักสูตรและแผนการเรียนเพื่อสร้างตัวเลือกในฟอร์ม

**Request:** ไม่มี query parameters และไม่มี request body

**Response: `200 OK`** — ค่าตาม configuration ปัจจุบัน:

```json
{
  "programs": [
    { "program": "IT", "tracks": ["coop", "nocoop"] },
    { "program": "DSBA", "tracks": ["coop", "nocoop"] },
    { "program": "BIT", "tracks": ["coop", "nocoop"] },
    { "program": "AIT", "tracks": ["default"] },
    { "program": "GENED", "tracks": ["default"] }
  ]
}
```

| Field | Type | ความหมาย |
|---|---|---|
| `programs` | array of objects | รายการหลักสูตรที่กำหนดไว้ในระบบ |
| `programs[].program` | string | รหัสหลักสูตร ใช้ส่งต่อใน request ของ `/api/ask` |
| `programs[].tracks` | array of strings | แผนการเรียนที่เลือกได้ของหลักสูตรนั้น |

รายการนี้มาจาก configuration ไม่ได้ยืนยันว่าไฟล์ฐานข้อมูลทุกหลักสูตรพร้อมใช้งาน
Frontend ต้องใช้รายการที่ API คืนมา ไม่กำหนดตัวเลือกตายตัวใน JavaScript
หากโหลดไม่สำเร็จ รายการหลักสูตรว่าง หรือหลักสูตรเริ่มต้นไม่มีแผนการเรียน
UI แสดง `error` และข้อความให้รีเฟรชหน้าเว็บ; ปุ่มถามจะปิดอยู่หากตัวเลือกยังไม่พร้อม

### 2. POST /api/ask

**หน้าที่:** รับคำถาม เลือกฐานข้อมูลตามหลักสูตรและแผน ตรวจ rules/cache และให้โมเดลเลือก intent/คำค้นเมื่อจำเป็น
โค้ด compile SQL อ่านฐานข้อมูล แล้วส่งคำตอบพร้อมผลข้อมูล เลขหน้าอ้างอิง และเวลาประมวลผลกลับมา

คำถามเปรียบเทียบ เช่น `เปรียบเทียบหน่วยกิตรวมและจำนวนปี IT กับ DSBA` ใช้ชื่อ 2 หลักสูตรในข้อความเป็นหลัก ผ่านกฎที่ไม่เรียก Qwen รองรับเฉพาะหน่วยกิตรวมทางการและจำนวนปี; `rows` มี `program`, `track` และหัวข้อที่ขอ เพื่อให้ UI แสดงบริบทจริง แม้หลักสูตรในฟอร์มต่างจากข้อความ แผนชัดเจนในคำถามมีผลก่อนฟอร์ม; แผนเดียวเลือกอัตโนมัติ และกรณีกำกวมตอบให้ระบุเพิ่มโดยไม่ query

**Request header:** `Content-Type: application/json`

| Field | Type | Required | เงื่อนไข |
|---|---|---|---|
| `question` | string | ใช่ | 2–500 ตัวอักษร; Frontend ตัดช่องว่างหัวท้ายก่อนส่ง |
| `program` | string | ใช่ | อย่างน้อย 2 ตัวอักษร; คำถามทั่วไปต้องอยู่ในรายการระบบ ส่วนการเปรียบเทียบใช้ targets ที่ตรวจจากข้อความ |
| `track` | string หรือ null | ตามหลักสูตร | คำถามทั่วไปเลือกแผนของ program; การเปรียบเทียบใช้เป็นค่าแผนสำรองของแต่ละ target |

Backend ตัดช่องว่างหัวท้ายและแปลง `program` เป็นตัวพิมพ์ใหญ่ และ `track` เป็นตัวพิมพ์เล็ก
สำหรับคำถามทั่วไป หากมีแผนเดียว ระบบเลือกแผนนั้นให้เมื่อไม่ส่ง `track` หรือส่ง null
แต่ข้อความว่าง `""` ไม่ถือเป็นการละค่าและจะถูกปฏิเสธ
Frontend ปัจจุบันส่งทั้ง `program` และ `track` จากตัวเลือกเสมอ

**ตัวอย่าง request:**

```json
{
  "question": "หลักสูตรนี้มีหน่วยกิตรวมทั้งหมดเท่าไร",
  "program": "DSBA",
  "track": "nocoop"
}
```

**Response: `200 OK`** — ตัวอย่างข้อมูลสมมติ ไม่ใช่การยืนยันจำนวนหน่วยกิตจริง:

```json
{
  "question": "หลักสูตรนี้มีหน่วยกิตรวมทั้งหมดเท่าไร",
  "sql": "SELECT total_credits FROM program",
  "rows": [{ "total_credits": 120 }],
  "answer": "หลักสูตรนี้มีหน่วยกิตรวม 120 หน่วยกิต"
}
```

| Field | Type | ความหมาย / จุดแสดงใน UI |
|---|---|---|
| `question` | string | คำถามที่ Backend ได้รับ |
| `sql` | string | SQL ที่ใช้หรือพยายามใช้; แสดงใน `#sql` |
| `rows` | array of objects | ผลจากฐานข้อมูล; แสดงตารางใน `#rows-table` และ JSON ใน `#rows` ภายในส่วนพับข้อมูลประกอบ |
| `answer` | string | คำตอบหรือคำอธิบายผล; แสดงใน `#answer` |
| `citations` | array of objects; ค่าเริ่มต้น `[]` | `source`, `pages` และขอบเขตหลักสูตร/แผน/วิชา/ปี/เทอม; แสดงใน `#answer-citations` |
| `processing_ms` | number หรือ null; ค่าเริ่มต้น null | เวลาฝั่ง API ตั้งแต่เข้า route ถึงหลัง `model.ask()` จบ; แสดงใน `#processing-time` |
| `performance` | object หรือ null; ค่าเริ่มต้น null | เวลาแยกขั้น เส้นทาง cache/rules/Qwen และ counters สำหรับผู้ดูแล ตรวจได้ผ่าน API/Network; ดู [handoff](../lab10_fastapi/curriculum_app/HANDOFF.md) |

Frontend วัดเวลาผู้ใช้รอด้วย `performance.now()` ตั้งแต่ก่อน fetch ถึงหลัง render ใน `#response-time` และไม่คำนวณผลต่างเป็นเวลาเครือข่าย รองรับ API เก่าสี่ฟิลด์โดยซ่อนเวลาฝั่ง API และแจ้งว่าไม่มีเลขหน้าเมื่อมีผลค้น

- คอลัมน์ในแต่ละ object ของ `rows` เปลี่ยนตาม SQL และค่าในคอลัมน์อาจเป็น null
- จำนวนแถวที่คืนถูกจำกัดด้วย `CURRICULUM_MAX_ROWS` (ค่าเริ่มต้น 100) ไม่ใช่จำนวนแถวทั้งหมดในฐานข้อมูล
- หากไม่พบข้อมูล ยังคงตอบ `200` โดย `rows` เป็น `[]` และ `answer` แจ้งว่าไม่พบข้อมูล
- คำถามเกี่ยวกับ metadata ที่ไม่รองรับของ GENED อาจตอบ `200` พร้อม `rows: []` และคำอธิบายข้อจำกัด
- ผล `200` ที่มีโครงสร้างถูกต้องทำให้ UI เป็น `success` แม้ไม่มีแถวข้อมูล

### Error contract ของ POST /api/ask

| HTTP Status | สาเหตุ | รูปแบบ `detail` |
|---|---|---|
| `422 Unprocessable Entity` | ข้อมูลไม่ผ่าน Pydantic validation เช่นไม่มี question หรือ question สั้นเกินไป | array of objects |
| `422 Unprocessable Entity` | หลักสูตร/แผนไม่ถูกต้อง หรือไม่ส่งแผนสำหรับหลักสูตรที่มีหลายแผน | string |
| `422 Unprocessable Entity` | ValueError, JSON parsing error หรือ SQLite error ที่ route จับไว้ระหว่างประมวลผล | string |
| `503 Service Unavailable` | ไม่พบไฟล์ฐานข้อมูล หรือติดต่อ Ollama ไม่สำเร็จ | string |
| `504 Gateway Timeout` | เวลารวมของคำถามหรือ query เกินกำหนด | string |
| `502 Bad Gateway` | ผลโมเดลผิดรูปแบบและซ่อมไม่ได้ | string |
| `500 Internal Server Error` | SQL ที่ compile แล้วทำงานไม่สำเร็จ หรือข้อมูลเปรียบเทียบเปลี่ยนระหว่างอ่านทั้งสองรอบ | string |

ตัวอย่างข้อผิดพลาดจากการเลือกหลักสูตร (`422`):

```json
{
  "detail": "Unknown program"
}
```

ข้อความการเลือกแผนที่ Backend ใช้ ได้แก่ `Select a track for this program`
และ `Unknown track for this program`

ตัวอย่าง validation error เมื่อไม่ส่ง question (`422`; อาจมีรายละเอียดเพิ่มเติมตามเวอร์ชัน):

```json
{
  "detail": [
    {
      "type": "missing",
      "loc": ["body", "question"],
      "msg": "Field required",
      "input": { "program": "DSBA", "track": "nocoop" }
    }
  ]
}
```

ตัวอย่างติดต่อโมเดลไม่ได้ (`503`):

```json
{
  "detail": "ติดต่อ Ollama ไม่ได้"
}
```

**การจัดการใน Frontend:**

- `detail` เป็น string: แสดงข้อความนั้น
- `detail` เป็น array: อ่าน `loc` และ `msg` ของแต่ละรายการ แล้วรวมเป็นข้อความ
- HTTP ไม่สำเร็จและไม่มี detail ที่รองรับ: แสดงข้อความพร้อม HTTP status
- ตอบสำเร็จแต่ JSON อ่านไม่ได้ หรือ `answer`, `rows`, `sql` ผิดชนิด: เปลี่ยนเป็น `error`
- เครือข่ายขัดข้อง: แสดงข้อความติดต่อเซิร์ฟเวอร์ไม่ได้ ซึ่งอาจไม่มี HTTP response/status
- ข้อผิดพลาดที่ Backend ไม่ได้จับไว้อาจเป็น `500` และไม่รับประกัน JSON; Frontend ใช้ข้อความสำรองข้างต้น
- ไม่มีการ retry อัตโนมัติ ผู้ใช้กดถามอีกครั้งได้เมื่อหลักสูตรและแผนพร้อม

### UI state contract

| State | เหตุการณ์ | พฤติกรรม |
|---|---|---|
| `idle` | โหลดตัวเลือกสำเร็จ หรือผู้ใช้แก้คำถาม/เปลี่ยนตัวเลือก | พร้อมรับคำถาม ล้างผลเก่า |
| `loading` | กำลังโหลดหลักสูตรหรือรอคำตอบ | ปิดช่องกรอก ตัวเลือก และปุ่มถามเพื่อป้องกันส่งซ้ำ |
| `success` | ได้คำตอบที่ผ่านการตรวจรูปแบบจาก `/api/ask` | แสดง answer, rows, sql และเปิดให้ถามต่อ |
| `error` | API/เครือข่ายผิดพลาด ข้อมูลตอบกลับผิดรูปแบบ หรือคำถามที่ตัดช่องว่างแล้วสั้นเกินไป | แสดงข้อความผิดพลาด ล้างผลเก่า และเปิดให้ลองใหม่เมื่อตัวเลือกพร้อม |

สถานะควบคุมด้วย `setState(state, message)` ใน `app.js` และแสดงผ่าน
`#ui-status` / `data-state`; `aria-busy` บนฟอร์มบอกว่ากำลังประมวลผล
Frontend ยังไม่มีการกำหนด timeout หรือยกเลิก fetch ด้วย AbortController
จึงรอจน request สำเร็จหรือเกิดข้อผิดพลาด Backend ใช้ deadline ร่วมใน `model.ask()`
(ค่าเริ่มต้น 180 วินาที รวมการเรียกโมเดลซ้ำ) แต่เวลาฝั่ง browser รวม network/render
จึงไม่ถือ deadline ของ service เป็นเวลาสูงสุดของการรอหน้าเว็บ
