"""Read-only comparisons of two explicitly registered editions."""
from copy import deepcopy
import re
from .database import current_trace, database_revision, edition_metadata, resolve_edition, measure_stage, remaining_seconds
from .verified_rules import rules_revision

def compare_editions(service, question, program, track):
    from .model_service import (curriculum_edition_hints, _data_targets, _study_hints,
        _category_hints, _credit_hints, _data_coverage, _outside_quotes, DataQuery, DataContext,
        ComparisonTarget, ANSWER_CACHE_VERSION)
    hints = curriculum_edition_hints(question)
    if len(hints["editions"]) < 2:
        return None
    trace = current_trace()
    trace.plan_source, trace.intent = "rules", "data_query"
    def refusal(message, reason):
        trace.planning_diagnostics.update(reason_code=reason)
        return {"question":question,"sql":"","rows":[],"answer":message,"citations":[],
                "analysis":{"kind":"edition_comparison","complete":False,"answer_completeness":"partial"}}
    if len(hints["editions"]) != 2:
        return refusal("กรุณาระบุฉบับหลักสูตรสองฉบับสำหรับงานเปรียบเทียบนี้", "edition_target_count")
    clean = hints["question"]
    try:
        targets, body, spans = _data_targets(clean, service.catalog, program, track)
        if len(targets) != 1:
            return refusal("การเทียบข้ามฉบับนี้ใช้หลักสูตรและแผนเดียวกัน กรุณาระบุเป้าหมายให้ชัด", "ambiguous_edition_targets")
        target = targets[0]
        editions = [resolve_edition(service.config,target.program,x,from_year=True) for x in hints["editions"]]
    except ValueError as exc:
        return refusal(str(exc), "unavailable_edition")
    if editions[0] == editions[1]:
        return refusal("ปีที่ระบุอ้างถึงฉบับเดียวกัน หากต้องการฉบับแก้ไขต้องลงทะเบียน ID และฐานแยก", "same_resolved_edition")
    study = _study_hints(body)
    category = _category_hints(_outside_quotes(body))
    credit = _credit_hints(body)
    if category["category"] or category["course_type"] or credit["credits"] is not None or re.search(r'["“\']', body):
        return refusal("ตัวเปรียบเทียบข้ามฉบับยังไม่ใช้ตัวกรองหมวด/หน่วยกิต/คำค้นนี้ จึงไม่ทิ้งเงื่อนไขเพื่อเทียบ", "unsupported_edition_filter")
    source = "plan" if study["years"] or study["semesters"] or re.search(r"ในแผน|ตามแผน",body) else "course"
    spec = DataQuery(operation="course_sets",source=source,years=study["years"],semesters=study["semesters"],
                     terms=[{"year":y,"semester":s} for y,s in study["terms"]])
    for m in re.finditer(r"ฉบับ|หลักสูตรเก่า|หลักสูตรใหม่|ฉบับเดิม|ฉบับใหม่|เก่า|ใหม่|เดิม|แต่ไม่มี|ไม่มี|ไม่อยู่|ไม่ปรากฏ|ส่วนต่าง|แตกต่างกัน|ต่างกัน|ร่วมกัน|ร่วม|ทั้งสองฉบับ|ทั้งสองฝั่ง|ทั้งสอง|รายการวิชา|มีใน|อยู่ใน",body):
        spans.append(dict(start=m.start(),end=m.end(),owner="edition_set_operation"))
    unknown = _data_coverage(body,spans,spec)
    if unknown:
        return refusal("ยังตีความเงื่อนไขเปรียบเทียบ '" + " / ".join(unknown) + "' ไม่ครบ", "uncovered_edition_condition")
    if re.search(r"วิชาก่อน|ความสัมพันธ์|สิทธิ์|เทียบโอน|สองปริญญา|จัดแผน", body):
        return refusal("ยังไม่ใช้ส่วนต่างรหัสแทนการเทียบเงื่อนไขหรือสิทธิ์ข้ามฉบับ", "unsupported_edition_operation")
    both = bool(re.search(r"ทั้งสอง|แต่ละ|ส่วนต่าง|แตกต่าง|ต่างกัน", body))
    common_only = bool(re.search(r"รหัสร่วม|วิชาร่วม|มีร่วม|ร่วมกัน|อยู่ในทั้งสอง|มีในทั้งสอง",body)) and not re.search(r"ส่วนต่าง|เฉพาะ|ไม่มี|ไม่อยู่|แตกต่าง",body)
    if not (both or common_only or re.search(r"ไม่มี|ไม่อยู่|ไม่ปรากฏ|เฉพาะ",body)):
        return refusal("ต้องการรหัสร่วม หรือรหัสที่มีเฉพาะฉบับใด กรุณาระบุทิศทาง", "ambiguous_edition_set")
    services = [service._edition_service(x) for x in editions]
    try:
        databases = [s.catalog.resolve(target.program,target.track) for s in services]
    except ValueError as exc:
        return refusal(str(exc), "missing_edition_track")
    revisions = tuple(database_revision(db.path) for db in databases)
    key = ("cross_edition",question,target.program,target.track,tuple(editions),revisions,ANSWER_CACHE_VERSION,rules_revision())
    trace.answer_cache_checked = True
    cached = service.answer_cache.get(key)
    if cached is not None:
        trace.plan_source,trace.answer_cache_hit = "answer_cache",True
        return cached
    contexts, sql = [], []
    for edition, scoped, db in zip(editions,services,databases):
        remaining_seconds()
        lexicon = scoped.lexicon.snapshot(db)
        with measure_stage("query"):
            executed,snapshot = db.data_snapshot(lexicon["columns"],is_gened=target.program=="GENED")
        ctx = DataContext(ComparisonTarget(program=target.program,track=target.track,edition=edition),snapshot,spec)
        contexts.append(ctx);sql.append(executed)
    def selected(ctx):
        records = ctx.plan_rows() if source=="plan" else ctx.snapshot["courses"]
        return {r["code"]:r for r in records if re.fullmatch(r"[0-9]{8}",str(r.get("code", "")))}
    left,right = map(selected,contexts)
    common = sorted(left.keys() & right.keys())
    only = [sorted(left.keys()-right.keys()), sorted(right.keys()-left.keys())]
    rows = []
    chosen = [(0,common,"common")] if common_only else [(0,only[0],"first_only"),(1,only[1],"second_only")] if both else [(0,only[0],"first_only")]
    for index,codes,side in chosen:
        ctx=contexts[index]
        for code in codes:
            row=left[code] if index==0 else right[code]
            detail=ctx.courses.get(code,{})
            ctx.cite("study_plan" if source=="plan" else "course",row)
            if common_only:contexts[1].cite("study_plan" if source=="plan" else "course",right[code])
            rows.append({"program":target.program,"track":target.track,"edition":editions[index],
                         "edition_label":edition_metadata(service.config,editions[index],target.program)["label"],
                         "side":side,"code":code,"name_th":detail.get("name_th") or row.get("name_th"),
                         "credits":row.get("credits")})
    labels=[edition_metadata(service.config,x,target.program)["label"] for x in editions]
    answer=f"เปรียบเทียบ {target.program} แผน {target.track}: {labels[0]} กับ {labels[1]}\n"
    answer += f"ขอบเขต: {'รหัสจริงในแผนที่กรองแล้ว' if source=='plan' else 'รายวิชารหัสจริงทั้งหมด'} ไม่รวมช่องที่ยังไม่เลือกรหัส\n"
    answer += f"รหัสร่วม {len(common)}; เฉพาะ {labels[0]} {len(only[0])}; เฉพาะ {labels[1]} {len(only[1])}\n"
    answer += "\n".join(f"{r['code']} {r['name_th'] or ''} — {r['edition_label']}" for r in rows)
    citations=[]
    for scoped,ctx in zip(services,contexts):
        for citation in ctx.evidence.values():
            citation={**citation,"program":target.program,"track":target.track,"edition":ctx.target.edition}
            citations.append(scoped.documents.enrich(citation))
    response={"question":question,"sql":"\n\n".join(sql),"rows":rows,"answer":answer,"citations":citations,
              "scope":{"targets":[ctx.target.model_dump() for ctx in contexts]},
              "analysis":{"kind":"edition_comparison","operation":"course_sets","complete":True,"answer_completeness":"complete",
                          "targets":[{**ctx.target.model_dump(),"edition_label":label} for ctx,label in zip(contexts,labels)],
                          "result":{"common_codes":common,"first_only":only[0],"second_only":only[1]},
                          "source":source,"limitations":["ส่วนต่างรหัสไม่ใช่ผลเทียบโอนหรือเกณฑ์สองปริญญา"]}}
    if tuple(database_revision(db.path) for db in databases)!=revisions:
        raise RuntimeError("DB changed while comparing editions; retry the request")
    service.answer_cache.put(key,response)
    return deepcopy(response)
