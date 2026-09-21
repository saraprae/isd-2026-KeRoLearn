"""Run the Lab 7B -> Lab 8B workflow on Windows, macOS, or Linux."""

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
LAB7 = ROOT / "src" / "ocr_system" / "lab7b_curriculum.py"
LAB8 = ROOT / "src" / "ocr_system" / "lab8b_curriculum_db.py"
LAB7_OUT = ROOT / "work" / "lab7b_run"
LAB8_OUT = ROOT / "work" / "lab8b_run"

# lab7b_curriculum.py คือที่เดียวที่นิยาม RUN_REGISTRY (1 รอบ/1 ไฟล์ PDF + ช่วงหน้าที่ต้อง OCR)
# lab8b_curriculum_db.py คือที่เดียวที่นิยาม PROGRAM_PAGE_RANGES (ช่วงหน้าแยกตาม nocoop/coop)
# import ตรงจากสองไฟล์นั้นแทนที่จะพิมพ์ตัวเลขซ้ำที่นี่ แล้วตรวจว่าสองที่ไม่เพี้ยนจากกัน
# (ที่มาของบั๊ก --track ด้านล่าง คือมีคนเติม flag ที่นี่โดยไม่เช็คว่า lab8b รับได้จริงไหม)
sys.path.insert(0, str(LAB7.parent))
from lab7b_curriculum import RUN_REGISTRY, RUNS_BY_ID, PROGRAMS  # noqa: E402
from lab8b_curriculum_db import PROGRAM_PAGE_RANGES, SECTION_GT_SUFFIX  # noqa: E402


def check_page_ranges_consistent() -> None:
    """หน้าที่ Lab 7B อ่าน (RUN_REGISTRY) ต้องเท่ากับหน้าทุก section รวมกันใน PROGRAM_PAGE_RANGES"""
    def expand(ranges) -> set[int]:
        return {pg for a, b in ranges for pg in range(a, b + 1)}

    problems = []
    for r in RUN_REGISTRY:
        sections = PROGRAM_PAGE_RANGES.get(r.program)
        if sections is None:
            problems.append(f"{r.program}: ไม่มีใน PROGRAM_PAGE_RANGES ของ lab8b")
            continue
        a, b = expand(r.page_ranges), expand(sections.values())
        if a != b:
            problems.append(f"{r.program}: lab7b อ่าน {len(a)} หน้า แต่ lab8b นิยาม {len(b)} หน้า "
                            f"(ต่างกัน: {sorted(a ^ b)[:8]}...)")
    if problems:
        raise SystemExit("❌ ช่วงหน้าใน RUN_REGISTRY กับ PROGRAM_PAGE_RANGES ไม่ตรงกัน:\n  "
                         + "\n  ".join(problems))


GT_ALIASES = {"GENED": ["general_education_ground_truth.json", "general_education.json"]}


def find_plan_gt(gt_dir: str | None, program: str, section: str | None) -> Path | None:
    """
    หาไฟล์เฉลยของโปรแกรม (หลังแยกแผนแล้ว) เช่น
        IT + nocoop -> IT_academic_plan_no_coop.json
        IT + coop   -> IT_academic_plan_coop.json
        AIT         -> AIT_academic_plan.json
    """
    if not gt_dir or not Path(gt_dir).is_dir():
        return None
    names = ([f"{program}_academic_plan_{SECTION_GT_SUFFIX[section]}.json",
              f"{program}_academic_plan_{section}.json"]
             if section else [f"{program}_academic_plan.json", f"{program}.json"])
    by_lower = {f.name.lower(): f for f in Path(gt_dir).glob("*.json")}
    if not section:
        # เฉลยที่ชื่อไม่ขึ้นต้นด้วยชื่อโปรแกรม (เช่น GENED)
        names += GT_ALIASES.get(program.upper(), [])
    for n in names:
        if n.lower() in by_lower:
            return by_lower[n.lower()]
    return None


def run(*args: object, dry_run: bool = False) -> None:
    cmd = [sys.executable, *(str(x) for x in args)]
    if dry_run:
        print("  [dry-run] " + " ".join(cmd))
        return
    subprocess.run(cmd, cwd=ROOT, check=True)


def run_single(args: argparse.Namespace) -> None:
    """
    โหมดไฟล์เดียวแบบเดิม — พฤติกรรมเหมือนสคริปต์เดิมทุกประการ

    ทำงานเมื่อไม่ได้ระบุ --run/--program/--all-runs เลย เพื่อไม่ให้คำสั่งเดิม
    ที่มีคนเคยใช้อยู่ (หรือสคริปต์อื่นที่เรียก run_lab8b.py แบบเดิม) พังไปเฉย ๆ
    """
    LAB7_OUT.mkdir(parents=True, exist_ok=True)
    LAB8_OUT.mkdir(parents=True, exist_ok=True)

    if not args.skip_lab7:
        lab7_cmd = [
            LAB7,
            "-i", args.input,
            "-g", args.gt,
            "-p", "vlm",
            "-o", LAB7_OUT,
        ]
        if args.pages:
            lab7_cmd.extend(["--pages", args.pages])
        run(*lab7_cmd, dry_run=args.dry_run)

    predictions = [LAB7_OUT / "pred_vlm.json", LAB7_OUT / "pred_markdown.json"]
    prediction = next((p for p in predictions if p.exists()), None)
    if prediction is None:
        if args.dry_run:
            prediction = predictions[0]
        else:
            raise SystemExit("ไม่พบ pred_vlm.json หรือ pred_markdown.json ใน work/lab7b_run")

    run(LAB8, "schema", "-o", LAB8_OUT / "schema", dry_run=args.dry_run)

    import_cmd = [LAB8, "import-lab7b", "-i", prediction,
                 "-o", LAB8_OUT / "curriculum.json",
                 "--program-id", args.program_id]
    if args.program_name:
        import_cmd += ["--program-name", args.program_name]
    if args.total_credits is not None:
        import_cmd += ["--total-credits", args.total_credits]
    if args.years is not None:
        import_cmd += ["--years", args.years]
    # เดิมมี "--track", "coop" ต่อท้ายตรงนี้ — ตัดออกแล้ว
    # import-lab7b ของ lab8b_curriculum_db.py ไม่มี argument นี้ ใส่ไปจะขึ้น
    # "unrecognized arguments: --track coop" แล้วทั้ง subprocess ล้มทันที
    # ความหมาย nocoop/coop สื่อผ่าน --program-id (เช่น "DSBA-coop") อยู่แล้ว
    run(*import_cmd, dry_run=args.dry_run)

    run(LAB8, "load", "-i", LAB8_OUT / "curriculum.json",
        "-d", LAB8_OUT / "curriculum.db", "--replace", dry_run=args.dry_run)
    run(LAB8, "verify", "-d", LAB8_OUT / "curriculum.db",
        "-o", LAB8_OUT / "verify.json", dry_run=args.dry_run)

    gold = LAB8_OUT / "gold_questions.json"
    sample = LAB7_OUT / "gold_questions_gt.json"
    if not gold.exists() and sample.exists():
        shutil.copyfile(sample, gold)
    if not args.dry_run and (not gold.exists()
                             or len(json.loads(gold.read_text(encoding="utf-8"))) < 30):
        print(f"\nเพิ่มคำถามใน {gold} ให้ครบ 30 ข้อ แล้วรัน:")
        print("python run_lab8b.py --skip-lab7")
        return

    run(LAB8, "eval", "-d", LAB8_OUT / "curriculum.db",
        "-q", gold, "-o", LAB8_OUT / "eval_result.json", dry_run=args.dry_run)
    print(f"\nเสร็จแล้ว: {LAB8_OUT}")


def read_manifest(lab8_out: Path, program: str, dry_run: bool) -> list[dict] | None:
    """
    อ่าน manifest.json ที่ import-lab7b เขียนไว้ — นี่คือแหล่งความจริงว่าแยกออกมากี่โปรแกรม
    (ไม่ hardcode ตาม RUN_REGISTRY: IT/DSBA/BIT ได้ 2 โปรแกรม, AIT/GENED ได้ 1)
    """
    mpath = lab8_out / "manifest.json"
    if mpath.exists():
        return json.loads(mpath.read_text(encoding="utf-8"))["programs"]
    if dry_run:
        # dry-run ไม่ได้รัน import จริงจึงไม่มี manifest — ประมาณจากตารางช่วงหน้าเพื่อโชว์คำสั่ง
        sections = [k for k in PROGRAM_PAGE_RANGES.get(program, {}) if k in ("nocoop", "coop")]
        if sections:
            return [{"program_id": f"{program}_{sec}", "section": sec, "dir": sec,
                     "curriculum": f"{sec}/curriculum.json", "status": "ok"} for sec in sections]
        return [{"program_id": program, "section": None, "dir": ".",
                 "curriculum": "curriculum.json", "status": "ok"}]
    return None


def process_program(entry: dict, program: str, lab7_out: Path, lab8_out: Path,
                    gt_dir: str | None, dry_run: bool) -> bool:
    """load -> verify -> eval-gt -> eval ให้หนึ่งโปรแกรมที่แยกออกมาแล้ว"""
    pid = entry["program_id"]
    if entry.get("status") != "ok":
        print(f"  ❌ ข้าม {pid}: import ล้มเหลว — {entry.get('error', '?')}")
        return False

    pdir = lab8_out / entry["dir"]
    curriculum = lab8_out / entry["curriculum"]
    db = pdir / "curriculum.db"
    try:
        run(LAB8, "load", "-i", curriculum, "-d", db, "--replace", dry_run=dry_run)
        run(LAB8, "verify", "-d", db, "-o", pdir / "verify.json", dry_run=dry_run)
    except subprocess.CalledProcessError as e:
        print(f"  ❌ Lab 8B ล้มเหลวที่ {pid}: {e}")
        return False

    # เทียบเฉลยทีละแผน (เฉลย coop / no_coop แยกไฟล์กันอยู่แล้ว) — ไม่บังคับ พังไม่กระทบ DB
    gt_file = find_plan_gt(gt_dir, program, entry.get("section"))
    if gt_file is not None:
        try:
            run(LAB8, "eval-gt", "-p", curriculum, "-g", gt_file,
                "-o", pdir / "eval_gt.json", dry_run=dry_run)
        except subprocess.CalledProcessError as e:
            print(f"  ! eval-gt ล้มเหลวที่ {pid} (curriculum.db ยังใช้งานได้ปกติ): {e}")
    elif gt_dir:
        print(f"  (ไม่พบเฉลยของ {pid} ใน {gt_dir} — ข้าม eval-gt)")

    gold = pdir / "gold_questions.json"
    sample = lab7_out / "gold_questions_gt.json"
    if not gold.exists() and sample.exists():
        shutil.copyfile(sample, gold)
    if not dry_run and (not gold.exists()
                        or len(json.loads(gold.read_text(encoding="utf-8"))) < 30):
        print(f"  (ยังไม่ eval — เพิ่มคำถามใน {gold} ให้ครบ 30 ข้อ แล้วรัน: "
              f"python run_lab8b.py --skip-lab7 --run {program})")
        return True

    try:
        run(LAB8, "eval", "-d", db, "-q", gold, "-o", pdir / "eval_result.json",
            dry_run=dry_run)
    except subprocess.CalledProcessError as e:
        print(f"  ! eval ล้มเหลวที่ {pid} (curriculum.db ยังใช้งานได้ปกติ): {e}")

    print(f"  ✓ เสร็จ {pid}: {pdir}")
    return True


def process_lab8_stage(run_id: str, program_meta: str | None, gt_dir: str | None,
                       dry_run: bool) -> list[tuple[str, bool]]:
    """
    ทำสาย Lab 8B ให้หนึ่ง run_id (= หนึ่งไฟล์ PDF = หนึ่งโปรแกรม):
        schema -> import-lab7b --split-dir (แยก nocoop/coop จากเลขหน้า) -> อ่าน manifest
        -> ต่อโปรแกรมที่แยกได้: load -> verify -> eval-gt -> eval

    คืนรายการ (program_id, ผ่านหรือไม่) — IT/DSBA/BIT ได้ 2 รายการ, AIT/GENED ได้ 1

    แยกจาก Lab 7B โดยเจตนา: Lab 7B ทั้งชุดถูกวนอยู่ในตัว lab7b_curriculum.py เอง
    (--all-runs/--program/--run ของมัน) ที่นี่แค่หยิบผลลัพธ์มาทำต่อทีละรอบ
    """
    lab7_out = LAB7_OUT / run_id
    lab8_out = LAB8_OUT / run_id
    lab8_out.mkdir(parents=True, exist_ok=True)

    predictions = [lab7_out / "pred_vlm.json", lab7_out / "pred_markdown.json"]
    prediction = next((p for p in predictions if p.exists()), None)
    if prediction is None:
        if dry_run:
            prediction = predictions[0]
        else:
            print(f"  ❌ ไม่พบ pred_vlm.json/pred_markdown.json ใน {lab7_out} — ข้ามรอบนี้")
            return [(run_id, False)]

    import_cmd = [LAB8, "import-lab7b", "-i", prediction,
                  "--program", run_id, "--split-dir", lab8_out]
    if program_meta:
        import_cmd += ["--program-meta", program_meta]
    # ไม่มี --track ที่นี่เช่นกัน (ดูเหตุผลใน run_single) — nocoop/coop อยู่ใน program_id แล้ว
    # (IT_nocoop / IT_coop) และ import-lab7b เป็นคนตั้งให้เองจากการแยกตามเลขหน้า

    try:
        run(LAB8, "schema", "-o", lab8_out / "schema", dry_run=dry_run)
        run(*import_cmd, dry_run=dry_run)
    except subprocess.CalledProcessError as e:
        print(f"  ❌ Lab 8B ล้มเหลวที่รอบ {run_id}: {e}")
        return [(run_id, False)]

    entries = read_manifest(lab8_out, run_id, dry_run)
    if entries is None:
        print(f"  ❌ ไม่พบ {lab8_out / 'manifest.json'} — import-lab7b ไม่ได้เขียน manifest")
        return [(run_id, False)]
    print(f"  แยกได้ {len(entries)} โปรแกรม: {', '.join(e['program_id'] for e in entries)}")
    return [(e["program_id"], process_program(e, run_id, lab7_out, lab8_out, gt_dir, dry_run))
            for e in entries]


def run_batch(run_ids: list[str], args: argparse.Namespace) -> None:
    """
    รันหลาย run_id: Lab 7B รอบเดียวครอบทุกรอบ (ผ่าน batch mode ของ lab7b_curriculum.py
    เอง) แล้วค่อยวน Lab 8B ทีละ run_id — รอบหนึ่งพังไม่ทำให้รอบอื่นหยุด
    """
    LAB7_OUT.mkdir(parents=True, exist_ok=True)
    LAB8_OUT.mkdir(parents=True, exist_ok=True)
    if args.program_meta and not Path(args.program_meta).exists():
        raise SystemExit(f"❌ ไม่พบ --program-meta: {args.program_meta}")

    if not args.skip_lab7:
        lab7_cmd = [LAB7]
        if args.all_runs:
            lab7_cmd += ["--all-runs"]
        elif args.run:
            lab7_cmd += ["--run", *args.run]
        else:
            lab7_cmd += ["--program", *args.program]
        lab7_cmd += ["--input-dir", args.input_dir, "-o", LAB7_OUT, "-p", "vlm"]
        if args.gt_dir:
            lab7_cmd += ["--gt-dir", args.gt_dir]
        try:
            run(*lab7_cmd, dry_run=args.dry_run)
        except subprocess.CalledProcessError as e:
            print(f"  ! Lab 7B บางรอบอาจล้มเหลว (ดูสรุปด้านบน) — จะทำ Lab 8B ต่อ "
                  f"เฉพาะรอบที่มี pred_vlm.json จริงเท่านั้น: {e}")

    summary: list[tuple[str, bool]] = []
    for i, run_id in enumerate(run_ids, 1):
        print(f"\n{'=' * 70}\n  Lab 8B รอบ {i}/{len(run_ids)}: {run_id}\n{'=' * 70}")
        summary += process_lab8_stage(run_id, args.program_meta, args.gt_dir, args.dry_run)

    print(f"\n{'=' * 70}\n  สรุปผล\n{'=' * 70}")
    for run_id, ok in summary:
        print(f"  {'✓' if ok else '❌'} {run_id}")
    n_ok = sum(1 for _, ok in summary if ok)
    print(f"\n  ผ่าน {n_ok}/{len(summary)} โปรแกรม · output อยู่ใต้ {LAB8_OUT}/<run_id>/[nocoop|coop]/")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-lab7", action="store_true")

    legacy = parser.add_argument_group(
        "single-file mode", "ไม่ระบุ --run/--program/--all-runs = โหมดนี้ (พฤติกรรมเดิม)")
    legacy.add_argument("-i", "--input", default="data/input_C/dsba.pdf",
                        help="Path to input PDF file or directory")
    legacy.add_argument("--pages", type=str, default=None,
                        help="Specific pages to process (e.g. '1', '1-2', '1,3')")
    legacy.add_argument("-g", "--gt", default="data/ground_truth_C/DSBA_academic_plan_coop.json")
    legacy.add_argument("--program-id", default="DSBA-coop")
    legacy.add_argument("--program-name", default=None)
    legacy.add_argument("--total-credits", type=int, default=None)
    legacy.add_argument("--years", type=int, default=None)

    batch = parser.add_argument_group(
        "batch mode", "รันหลายโปรแกรม/แผนพร้อมกัน แต่ละรอบได้โฟลเดอร์ output แยกของตัวเอง")
    batch.add_argument("--run", nargs="+", choices=sorted(RUNS_BY_ID),
                       metavar="RUN_ID", help="ระบุรอบรันเจาะจง (1 รอบ/ไฟล์) เช่น --run IT DSBA")
    batch.add_argument("--program", nargs="+", choices=PROGRAMS,
                       metavar="PROGRAM", help="รันทุกรอบของโปรแกรมนี้ เช่น --program IT")
    batch.add_argument("--all-runs", action="store_true",
                       help="รันทุกรอบของทุกโปรแกรมใน RUN_REGISTRY")
    batch.add_argument("--input-dir", default="data/input")
    batch.add_argument("--gt-dir", default=None,
                       help="โฟลเดอร์ ground truth — มองหา <PROGRAM>_academic_plan*.json เช่น IT_academic_plan_coop.json, "
                            "IT_academic_plan_no_coop.json, AIT_academic_plan.json")
    batch.add_argument("--program-meta", default=None,
                       help="ไฟล์ JSON {program_id: {name, total_credits, years}} เช่น IT_nocoop, IT_coop, AIT "
                            "— ไม่ระบุจะปล่อยให้ Lab 8B คำนวณ total_credits/years เอง")
    parser.add_argument("--dry-run", action="store_true",
                        help="พิมพ์คำสั่งที่จะรันโดยไม่รันจริง (เช็คก่อนปล่อยรันจริงหลายชั่วโมง)")
    args = parser.parse_args()
    check_page_ranges_consistent()

    os.environ.update({
        "PYTHONUTF8": "1",
        "LAB7_CHUNK": "1",
        "LAB7B_NUM_CTX": "8192",
        "LAB7B_NUM_PREDICT": "2000",
        "LAB7B_OCR_NUM_CTX": "4096",
        "LAB7B_OCR_NUM_PREDICT": "1200",
    })

    if args.all_runs:
        run_ids = [r.run_id for r in RUN_REGISTRY]
    elif args.run:
        run_ids = list(args.run)
    elif args.program:
        run_ids = [r.run_id for r in RUN_REGISTRY if r.program in args.program]
    else:
        run_ids = None

    if run_ids is None:
        run_single(args)
    else:
        run_batch(run_ids, args)


if __name__ == "__main__":
    main()