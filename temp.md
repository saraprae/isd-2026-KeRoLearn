คำสั่งที่ใช้
    cd <PATH ของ ocr_system>
    .\venv\Scripts\Activate.ps1 

ต้องการรันแค่บางหน้าใหม่
# อันนี้คือเวลาที่แก้ logic แล้วไม่ต้องการให้เสียเวลารันทั้งเล่ม ผลมันจะไปออกที่ -o/<ที่เราเขียนไว้> เราก็ copy ผลลัพธ์ของส่วนนั้นไปแทนที่กับ pred_vlm, intermediate_vlm ได้ (ต้องใส่หน้าจริงที่ไม่ใช่หน้าที่เขียนใน pdf)
    python -m src.ocr_system.lab7b_curriculum -i data/input/BIT.pdf --pages 35 -p vlm -o work/page35_retry


งง รันคำสั่งแรกแล้วได้ 100 แต่คำสั่งสองไม่ได้
    python3 src\ocr_system\lab8b_curriculum_db.py eval-gt -p work\lab7b_run\AIT\pred_vlm.json -g data\ground_truth\AIT_academic_plan.json -o eval_gt.json
    python run_lab8b.py --run BIT --input-dir data/input --gt-dir data/ground_truth --skip-lab7
    