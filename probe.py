import base64, sys, requests, pymupdf

pdf, page = sys.argv[1], int(sys.argv[2])
png = pymupdf.open(pdf)[page - 1].get_pixmap(
    matrix=pymupdf.Matrix(150 / 72, 150 / 72)).tobytes("png")
r = requests.post("http://127.0.0.1:11434/api/chat", json={
    "model": "scb10x/typhoon-ocr1.5-3b", "stream": False,
    "messages": [{"role": "user", "content": "Extract all text from the image.",
                  "images": [base64.b64encode(png).decode()]}],
    "options": {"num_ctx": 4096, "num_predict": 1200, "temperature": 0.1}},
    timeout=900)
print(pdf, page, "->", r.status_code, r.text[:500])