"""บันทึกประวัติการกดส่ง FDH ลงไฟล์ append-only (1 บรรทัด = 1 ครั้งที่ส่ง)

ใช้เก็บสิ่งที่ FDH ไม่ได้เก็บให้: เรากดส่งไปกี่รอบ แต่ละรอบ txid/ผลอะไร
ponytail: jsonl ธรรมดา append ต่อท้าย — ผู้ใช้คนเดียวพอ ไม่ต้องมี DB/ล็อก
"""
import json
import os
from runtime_paths import HISTORY_PATH
import api_config

LOG = str(HISTORY_PATH)


def log(entry):
    entry = dict(entry)
    if "environment" not in entry:
        entry["environment"] = api_config.load().environment
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def load(environment=None):
    if not os.path.exists(LOG):
        return []
    out = []
    with open(LOG, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    entry = json.loads(line)
                    if environment is None or entry.get("environment", "UAT") == environment:
                        out.append(entry)
                except json.JSONDecodeError:
                    pass
    return out


def sent_vns(environment=None):
    """set ของ vn ที่เคยกดส่งสำเร็จ (อ่านจากไฟล์ เร็ว ไม่ยิงเน็ต) — ใช้ mark 'ส่งแล้ว' ตอนเปิด"""
    environment = environment or api_config.load().environment
    return {str(e["vn"]) for e in load(environment)
            if e.get("status") == "submitted" and e.get("vn") is not None}
