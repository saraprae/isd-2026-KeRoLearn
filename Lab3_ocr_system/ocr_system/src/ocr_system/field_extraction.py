import re


def extract_common_fields(text: str) -> dict:
    """Basic rule-based extraction. Customize regexes for your document type."""
    fields = {}

    email = re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", text)
    if email:
        fields["email"] = email.group(0)

    date = re.search(r"\b(?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}-\d{2}-\d{2})\b", text)
    if date:
        fields["date"] = date.group(0)

    student_id = re.search(r"\b\d{8,12}\b", text)
    if student_id:
        fields["numeric_id"] = student_id.group(0)

    phone = re.search(r"(?:\+?66|0)\d{8,9}\b", text.replace("-", ""))
    if phone:
        fields["phone"] = phone.group(0)

    return fields
