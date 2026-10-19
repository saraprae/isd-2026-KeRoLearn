"""Bounded wording roles shared by parser/coverage; no DB or model decisions."""
import re


def _course_operand(body, patterns, operation):
    for pattern in patterns:
        match = re.fullmatch(r"\s*[:：]?\s*" + pattern + r"\s*[?？]?\s*", body, re.I)
        if match is None:continue
        raw=match["name"];name=raw.strip();start=match.start("name")+len(raw)-len(raw.lstrip())
        if name[:1] not in {'"','“',"'"}:
            name=re.sub(r"\s*\(\s+\)\s*$","",name).rstrip()
            name=re.sub(r"\s+(?:ใน|ของ)\s*$","",name).rstrip()
        quoted=re.fullmatch(r'"([^"\n]+)"|“([^”\n]+)”|\'([^\'\n]+)\'',name)
        if quoted:
            name=next(v for v in quoted.groups() if v is not None);start+=1
        if not 3<=len(name)<=120:continue
        if not quoted and (re.search(r"คำว่า|ที่ชื่อ|ชื่อมี|ทั้งหมด|ทุกหมวด|หมวด|เทอม|ปี\s*[0-9]|ยกเว้น|ไม่รวม|ไม่เอา|อย่างน้อย|ไม่เกิน|หน่วยกิต|เกณฑ์|กี่|/",name)
                           or re.match(r"(?:ถ้า|ก่อน|ต้อง|มีวิชา|รวม|จำนวน|ขอ|แผน)",name)):
            continue
        return dict(start=start,end=start+len(name),text=name,operation=operation,
                    **({"recursive":bool(match["recursive"])} if "recursive" in match.groupdict() else {}),
                    request_spans=[dict(start=0,end=match.start("name"),owner="requested_operation"),
                                   dict(start=start+len(name),end=len(body),owner="requested_operation")])
    return None


def scalar_course_operand(body):
    # Each suffix fixes one requested output; filters/extra clauses cannot hide in it.
    scalar = _course_operand(body,[
        r"รหัสวิชา\s*(?P<name>[0-9]{8})\s*ชื่อ(?:ว่า)?อะไร",
        r"(?:จำนวน)?หน่วยกิตของ\s*(?:วิชา\s*)?(?P<name>.+?)\s*(?:เท่าไร|เท่าไหร่)",
        r"(?:รหัส|ชื่อ)(?:ของ)?วิชา\s*(?P<name>.+?)\s*(?:คืออะไร|อะไร)",
        r"วิชา\s*(?P<name>.+?)\s*(?:มี|ต้องเรียน)?กี่หน่วยกิต",
        r"(?:วิชา\s*)?(?P<name>.+?)\s*(?:เป็นวิชาบังคับหรือวิชาเลือก|เป็นวิชาบังคับหรือไม่|อยู่(?:ใน)?หมวดวิชา(?:ใด|อะไร))",
        r"วิชา\s*(?P<name>.+?)\s*ใช้เวลาเรียน(?:ทฤษฎี|บรรยาย)\s*[,/]?\s*ปฏิบัติ\s*(?:และ|[,/])?\s*(?:ศึกษาเอง|ศึกษาด้วยตนเอง)\s*อย่างละกี่ชั่วโมง",
        r"(?:วิชา\s*)?(?P<name>.+?)\s*ใช้รหัสอะไร",
        r"วิชา\s*(?P<name>.+?)\s*มีชั่วโมงบรรยาย-ปฏิบัติ-ศึกษาด้วยตนเองเท่าไร",
    ],"lookup")
    if scalar:return scalar
    return _course_operand(body,[
        r"(?:วิชา\s*)?(?P<name>.+?)\s*(?:มี)?วิชาที่ต้องเรียนพร้อมกัน(?:หรือไม่|ไหม)",
        r"(?:วิชา\s*)?(?P<name>.+?)\s*(?:ต้องเรียนพร้อมกับวิชาใด|มีวิชาควบอะไรบ้าง)",
    ],"relations") or relationship_course_operand(body)


def registration_course_operand(body):
    return _course_operand(body,[
        r"ถ้า(?:ยัง)?ไม่ผ่านวิชาก่อนของ\s*(?P<name>.+?)\s*(?:จะ)?ลง(?:ทะเบียน|เรียน)?ได้(?:ไหม|หรือไม่)",
        r"(?:ยัง)?ไม่ผ่านวิชาที่ต้องเรียนก่อน\s*(?P<name>.+?)\s*(?:จะ)?ลง(?:ทะเบียน|เรียน)?ได้(?:ไหม|หรือไม่)",
        r"(?:ยัง)?ไม่ผ่านวิชาก่อน\s*(?P<name>.+?)\s*(?:จะ)?ลง(?:ทะเบียน|เรียน)?ได้(?:ไหม|หรือไม่)",
    ],"registration_conditions")


def rejection_diagnostics(message, intent):
    rules=[
        (r"ไม่มี(?:ฐาน|แผน)|แผนที่รองรับ|แผนที่มี", "capability", "unavailable_comparison_target"),
        (r"ฉบับ|เวอร์ชัน", "scope", "unresolved_curriculum_edition"),
        (r"ชื่อ.*หลาย|รหัส.*หลาย", "input", "ambiguous_course_name"),
        (r"ไม่พบ.*(?:รหัส|ชื่อวิชา)", "input", "course_not_found"),
        (r"สอง|2–3|ไม่ซ้ำกัน", "input", "invalid_comparison_targets"),
        (r"ระบุแผน|แผนเดียวร่วมกัน", "scope", "unresolved_comparison_track"),
        (r"กรอง.*(?:ประเภท|หมวด)|ปี/เทอม|ปี.*เทอม", "capability", "unsupported_comparison_filter"),
        (r"ส่วน.*ไม่ได้|ตีความ", "coverage", "uncovered_comparison_condition"),
        (r"เปรียบเทียบได้เฉพาะ|ส่วนต่างแผนรองรับ|ยังไม่รองรับ", "capability", "unsupported_comparison_operation"),
    ]
    stage,reason=next(((stage,reason) for pattern,stage,reason in rules if re.search(pattern,message)),
                      ("capability","unsupported_operation") if intent=="unsupported" else ("input","missing_or_ambiguous_input"))
    return dict(failure_stage=stage,reason_code=reason,complete=False)


def literal_searches(question):
    """Read separate search clauses; an AND inside a literal is left intact."""
    pattern=re.compile(r"(?P<label>ชื่อ(?:ภาษา)?(?:อังกฤษ|ไทย)?|คำอธิบาย)\s*(?:ที่)?(?P<op>ไม่มี|มี|กล่าวถึง|เกี่ยวกับ)?\s*(?:คำว่า|คำ)\s*(?P<term>\"[^\"\n]+\"|“[^”\n]+”|'[^'\n]+'|.+?)(?=\s*(?:และ|หรือ)\s*(?:ชื่อ|คำอธิบาย)|\s*(?:แต่|และ)\s*(?:ไม่เอา|ไม่รวม|ยกเว้น|ไม่เกิน|ชั่วโมง|มี\s*[0-9])|\s+พร้อม|\s*(?:มีอะไรบ้าง|มีวิชาไหนบ้าง|เรียง)|[?？]?$)",re.I)
    result=[]
    for m in pattern.finditer(question):
        raw=m['term'].strip();term=raw[1:-1] if raw[:1] in {'"','“',"'"} else raw
        if not term:continue
        label=m['label'];field='name_en' if 'อังกฤษ' in label else 'name_th' if 'ไทย' in label else 'description_th' if label=='คำอธิบาย' else 'name_any'
        result.append(dict(field=field,term=term,exclude=m['op']=='ไม่มี',start=m.start(),end=m.end()))
    return result


def course_candidates(name, lexicon):
    """Share exact/literal DB matching; whitespace variation never picks one candidate."""
    key=lambda value:re.sub(r"\s+","",value).casefold()
    wanted=key(name)
    names=lexicon.get("names",{})
    exact={code for stored,values in names.items() if key(stored)==wanted for code in values}
    if exact:return exact
    aliases={code for pattern,values in lexicon.get("alias_patterns",[]) if pattern.fullmatch(name) for code in values}
    return aliases | {code for stored,values in names.items() if wanted in key(stored) for code in values}

# A complete wording frame, shared by rules, coverage, validation and model hints.
# The position of NAME determines direction; the word ต่อ alone never does.
def relationship_course_operand(body):
    ask = r"(?:วิชา|ตัว)?(?:อะไร|ไหน|ใด)"
    recursive = r"(?:ทั้งสาย|ทุกทอด|ทางอ้อม)"
    patterns = [
        (rf"ก่อนเรียน\s*(?:วิชา\s*)?(?P<name>.+?)\s*ต้อง(?:ผ่าน|เรียน)\s*{ask}(?:มา)?(?:ก่อน)?(?:บ้าง)?", "pre", "before"),
        (r"ต้องลงวิชา(?:อะไร|ไหน)ไว้ก่อนเพื่อ(?:ให้)?เรียน\s*(?:วิชา\s*)?(?P<name>.+?)(?:ได้)?", "pre", "before"),
        (rf"(?:วิชา\s*)?(?P<name>.+?)\s*ต้อง(?:ผ่าน|เรียน)\s*{ask}(?:มา)?ก่อน(?:บ้าง)?", "pre", "before"),
        (rf"(?:วิชา\s*)?(?P<name>.+?)\s*มีวิชาบังคับก่อน\s*(?:อะไร|ใด|ไหน)(?:บ้าง)?", "pre", "before"),
        (rf"(?:วิชา\s*)?(?P<name>.+?)\s*ต่อจาก\s*{ask}(?:บ้าง)?", "pre", "before"),
        (r"เงื่อนไขวิชาก่อนของ\s*(?P<name>.+?)\s*คืออะไร", "pre", "before"),
        (rf"(?:วิชา\s*)?(?P<name>.+?)\s*ต้องเรียนควบกับ\s*{ask}(?:บ้าง)?", "co", "before"),
        (rf"(?:วิชา\s*)?(?P<name>.+?)\s*เป็นวิชา(?:บังคับ)?ก่อนของ\s*{ask}(?:บ้าง)?", "pre", "after"),
        (rf"{ask}(?:บ้าง)?\s*ต่อจาก\s*(?:วิชา\s*)?(?P<name>.+?)", "pre", "after"),
        (rf"{ask}\s*ต้องผ่าน\s*(?:วิชา\s*)?(?P<name>.+?)\s*ก่อน", "pre", "after"),
    ]
    for pattern, kind, direction in patterns:
        # Capture depth separately: it is an executed option, not ignored filler.
        operand = _course_operand(body, [pattern + rf"\s*(?P<recursive>{recursive})?\s*(?:ครับ|ค่ะ|หน่อย)?"], "relations")
        if operand:
            return {**operand, "relation_kind":kind, "direction":direction}
    return None


def ambiguous_relationship_operand(body):
    """Only a bounded question with no before/after marker is ambiguous."""
    return _course_operand(body, [
        r"(?:วิชา\s*)?(?P<name>.+?)\s*ต่อ(?:วิชา)?(?:อะไร|ไหน|ใด)(?:บ้าง)?",
    ], "relations")
