"""ขั้นที่ 4: แปลง OPD visit 1 ราย -> FDH v3.0.0 JSON (READ-ONLY query)

ใช้:  python build_payload.py [VN]        # สร้าง payload.json + validate ยอดเงิน
      python build_payload.py --selfcheck # ทดสอบ logic รวมเงิน/บาลานซ์ โดยไม่ต่อ DB

ยังไม่ส่งเข้า FDH — แค่สร้างไฟล์ให้ตรวจก่อน (ส่งจริงค่อยใช้ขั้นที่ 5)

⚠️ 2 รหัสมาตรฐานที่ต้องยืนยันกับสเปก FDH (ตั้งค่าตั้งต้นไว้ แก้ที่ค่าคงที่ข้างล่าง):
   - CHRGITEM_MAP : หมวดค่าใช้จ่าย 2 หลัก  (ตอนนี้ใช้ std_group 16 หมวดของ สปสช.)
   - CLINIC_CODE  : รหัสคลินิก 5 หลักของแผนก
"""
import decimal
import json
import sys
from decimal import Decimal

import get_token  # reuse load_env() + UTF-8 stdout

_ENV = get_token.load_env()
HCODE = _ENV.get("FDH_HOSPITAL_CODE") or "10731"
HIS_NAME, HIS_VERSION = "HOSxP", "3.x"
HOSPITAL_NAME = _ENV.get("FDH_HOSPITAL_NAME") or "โรงพยาบาลพหลพลพยุหเสนา"

# --- รหัสที่ยังต้องยืนยันกับสเปก FDH ---
# ponytail: ตั้งต้น chrgItem = std_group (16 หมวด สปสช.) — ถ้า FDH ใช้รหัสหมวดชุดอื่น แก้ที่นี่
CHRGITEM_MAP = {  # std_group(16 หมวด) -> chrgItem ที่ส่ง FDH
    "01": "01", "02": "02", "03": "03", "04": "04", "05": "05", "06": "06",
    "07": "07", "08": "08", "09": "09", "10": "10", "11": "11", "12": "12",
    "13": "13", "14": "14", "15": "15", "16": "16",
}
# ponytail: รหัสคลินิก 5 หลักของ ER ตั้งต้น 00500 — ยืนยันกับตารางคลินิก สนย./FDH
CLINIC_CODE = "00500"

# std_group -> itemCat ของ FDH (DRUG/LAB/IMAGING/PROC/SERVICE/SUPPLY)
ITEMCAT_MAP = {
    "03": "DRUG", "04": "DRUG", "05": "SUPPLY", "07": "LAB", "08": "IMAGING",
    "09": "PROC", "10": "SUPPLY", "11": "PROC", "12": "SERVICE",
}

TWO = Decimal("0.01")
decimal.getcontext().rounding = decimal.ROUND_HALF_EVEN  # banker's ตามกฎ FDH


def money(x):
    """ปัด 2 ตำแหน่งแบบ half-to-even, คืน float สำหรับ JSON (เป็น number ไม่ใช่ string)"""
    return float(Decimal(str(x or 0)).quantize(TWO))


def dt(d, t):
    """รวม date + time(string 'H:MM:SS') -> 'YYYY-MM-DDThh:mm:ss' (เลขศูนย์นำครบ)"""
    if not d:
        return None
    hh, mm, ss = (str(t or "0:0:0").split(":") + ["0", "0", "0"])[:3]
    return f"{d}T{int(hh):02d}:{int(mm):02d}:{int(ss):02d}"


def prune(d):
    """ตัด field ที่เป็น None/'' ออก (กฎ FDH ข้อ 4) — ไม่แตะ list/0/False"""
    if isinstance(d, dict):
        return {k: prune(v) for k, v in d.items() if v not in (None, "")}
    if isinstance(d, list):
        return [prune(x) for x in d]
    return d


def build(data):
    """data = dict ดิบจาก DB -> FDH visit dict.  แยกออกมาเพื่อ selfcheck ได้โดยไม่ต่อ DB"""
    o, p, scr = data["ovst"], data["patient"], data.get("opdscreen")
    items = data["opitemrece"]
    license_no = data["doctor_license"]
    income_std = data["income_std"]      # income code -> std_group(2 หลัก)
    item_name = data["item_name"]        # icode -> ชื่อรายการ
    invoice = f"INV-{o['vn']}"
    sdate = str(o["vstdate"])

    # ---- จัดกลุ่มค่าใช้จ่ายตาม chrgItem ----
    groups = {}
    for it in items:
        std = income_std.get(str(it.get("income")), "16")  # ไม่รู้หมวด -> อื่นๆ
        chrg = CHRGITEM_MAP.get(std, std)
        g = groups.setdefault(chrg, {"std": std, "items": []})
        amt = money(it["sum_price"])
        g["items"].append({
            "descript": item_name.get(it["icode"], it["icode"]),
            "qty": float(it.get("qty") or 0),
            "unitPrice": money(it.get("unitprice")),
            "chargeAmt": amt,
            "serviceDate": sdate,
            "itemCat": ITEMCAT_MAP.get(std, "SERVICE"),
            # ponytail: ไม่มีคอลัมน์ TMT ใน HOSxP รุ่นนี้ -> ใช้ localCode/LCCode ทั้งหมด
            "codeSys": "LCCode",
            "localCode": it["icode"],
            "stdCode": it["icode"],
            "reimbPrice": money(it.get("unitprice")),
            "reimburser": "NHSO",
            "dispStat": "1",
        })

    cha, cht_total = [], Decimal("0")
    for chrg, g in sorted(groups.items()):
        amount = sum((Decimal(str(i["chargeAmt"])) for i in g["items"]), Decimal("0"))
        cht_total += amount
        cha.append({
            "chrgItem": chrg,
            "amount": float(amount),
            "claimAmt": float(amount),   # ponytail: UCS สมมติเบิกได้เต็ม -> claimAmt=amount, paid=0
            "paid": 0.00,
            "itemCount": len(g["items"]),
            "date": sdate,
            "invoiceNo": invoice,
            "items": g["items"],
        })
    cht = [{
        "total": float(cht_total), "claimAmt": float(cht_total), "paid": 0.00,
        "date": sdate, "invoiceNo": invoice,
    }]

    # ---- diagnosis (เฉพาะ ICD-10 จริง = ขึ้นต้นด้วยตัวอักษร) ----
    diag = []
    for i, r in enumerate((x for x in data["ovstdiag"] if str(x["icd10"])[:1].isalpha()), 1):
        diag.append(prune({
            "icd10": r["icd10"], "diagType": str(r.get("diagtype") or ""),
            "professionId": license_no, "dateTime": dt(o["vstdate"], o["vsttime"]),
            "sequence": i,
        }))

    vitals = []
    if scr:
        vitals.append(prune({
            "dateTime": dt(scr.get("vstdate"), scr.get("vsttime")),
            "bodyTemp": float(scr["temperature"]) if scr.get("temperature") else None,
            "bpSystolic": int(scr["bps"]) if scr.get("bps") else None,
            "bpDiastolic": int(scr["bpd"]) if scr.get("bpd") else None,
            "pulseRate": int(scr["pulse"]) if scr.get("pulse") else None,
            "respiratoryRate": int(scr["rr"]) if scr.get("rr") else None,
        }))

    visit = {
        "patient": prune({
            "birthDate": str(p["birthday"]), "gender": str(p.get("sex") or ""),
            "hn": p["hn"], "id": p.get("cid"), "idType": "1",
            "maritalStatus": str(p.get("marrystatus") or "") or None,
            "nationality": str(p.get("nationality") or "") or None,
            "occupation": str(p.get("occupation") or "") or None,
            "name": prune({"prefix": p.get("pname"), "given": p.get("fname"),
                           "family": p.get("lname"),
                           "line": f"{p.get('pname','')}{p.get('fname','')} {p.get('lname','')}".strip()}),
            "address": prune({"state": p.get("chwpart"), "city": p.get("amppart"),
                              "district": p.get("tmbpart"), "line": p.get("informaddr")}),
        }),
        "encounter": {
            "type": "opd",
            "opd": prune({"clinic": CLINIC_CODE, "dateTime": dt(o["vstdate"], o["vsttime"]),
                          "seq": o["vn"]}),
            "clinical": prune({
                "chiefComplaint": scr.get("cc") if scr else None,
                # ponytail: น้ำหนัก 0 = ไม่ได้ชั่ง -> ตัดทิ้งตามกฎ FDH
                "bodyWeight": float(scr["bw"]) if scr and scr.get("bw") else None,
            }),
            "vitalSigns": vitals,
            "allergy": [], "presentIllness": [], "physicalExam": [],
            "diagnosisText": [], "diagnosisIcd10": diag,
            # ponytail: หัตถการ ICD-9/Lab/รังสี ส่งใน cha แล้ว ปล่อย [] ก่อนให้ผ่าน UAT แล้วค่อยขยาย
            "procedure": [], "lab": [], "radiology": [], "pathology": [], "vaccine": [],
        },
        "benefits": {
            "claim": prune({
                "hcode": HCODE, "hmain": o.get("hospmain"), "hsub": o.get("hospsub"),
                "inscl": "UCS", "uuc": "1", "permitNo": o.get("pttypeno"),
            }),
            "cht": cht, "cha": cha,
        },
    }
    return visit, cht_total


def validate(visit, cht_total):
    """เช็คกฎยอดเงิน 3 ชั้น (กฎ FDH ข้อ 2) — โยน AssertionError ถ้าไม่ตรง"""
    cha = visit["benefits"]["cha"]
    for c in cha:
        s = sum(Decimal(str(i["chargeAmt"])) for i in c["items"])
        assert s == Decimal(str(c["amount"])), f"Σitems {s} != cha.amount {c['amount']} ({c['chrgItem']})"
        assert c["itemCount"] == len(c["items"]), "itemCount ไม่ตรงจำนวน items"
    s_cha = sum(Decimal(str(c["amount"])) for c in cha)
    assert s_cha == cht_total, f"Σcha {s_cha} != cht.total {cht_total}"
    assert Decimal(str(visit["benefits"]["cht"][0]["total"])) == cht_total


def _selfcheck():
    data = {
        "ovst": {"vn": "V1", "vstdate": "2026-06-25", "vsttime": "9:5:7",
                 "hospmain": "10677", "hospsub": "07869", "pttypeno": "A1"},
        "patient": {"hn": "1", "birthday": "1974-06-13", "sex": "2", "cid": "x",
                    "pname": "นาง", "fname": "มาลี", "lname": "ก", "chwpart": "70",
                    "amppart": "01", "tmbpart": "14", "occupation": "403"},
        "opdscreen": {"vstdate": "2026-06-25", "vsttime": "9:5:7", "bw": 0,
                      "temperature": 36.4, "bps": 213, "bpd": 114, "pulse": 102, "rr": 20,
                      "cc": "x"},
        "ovstdiag": [{"icd10": "K210", "diagtype": "1"}, {"icd10": "8952", "diagtype": "2"}],
        "opitemrece": [
            {"icode": "A", "income": "81", "qty": 10, "unitprice": "2.25", "sum_price": "22.50"},
            {"icode": "B", "income": "81", "qty": 1, "unitprice": "15", "sum_price": "15.00"},
            {"icode": "C", "income": "08", "qty": 1, "unitprice": "200", "sum_price": "200.00"},
        ],
        "doctor_license": "ว41293",
        "income_std": {"81": "03", "08": "08"},
        "item_name": {"A": "ยา A", "B": "ยา B", "C": "X-ray"},
    }
    visit, tot = build(data)
    validate(visit, tot)
    assert tot == Decimal("237.50"), tot
    assert visit["encounter"]["diagnosisIcd10"][0]["icd10"] == "K210"
    assert len(visit["encounter"]["diagnosisIcd10"]) == 1, "ต้องตัดรหัสตัวเลข 8952 ออก"
    assert "bodyWeight" not in visit["encounter"]["clinical"], "น้ำหนัก 0 ต้องถูกตัด"
    drug_grp = [c for c in visit["benefits"]["cha"] if c["chrgItem"] == "03"][0]
    assert drug_grp["amount"] == 37.50 and drug_grp["itemCount"] == 2
    print("selfcheck OK — ยอดรวม 237.50, บาลานซ์ครบ 3 ชั้น, ตัดรหัส/น้ำหนักถูก")


def fetch(vn):
    import db
    c = db.connect()

    def q(sql, a=None):
        assert sql.lstrip().upper().startswith(("SELECT", "SET SESSION")), "อ่านอย่างเดียว"
        with c.cursor() as cur:
            cur.execute(sql, a)
            return cur.fetchall()
    try:
        q("SET SESSION TRANSACTION READ ONLY")
        ovst = q("SELECT * FROM ovst WHERE vn=%s", (vn,))
        if not ovst:
            sys.exit(f"ไม่พบ vn={vn}")
        o = ovst[0]
        items = q("SELECT * FROM opitemrece WHERE vn=%s", (vn,))
        incomes = tuple({str(i.get("income")) for i in items}) or ("",)
        icodes = tuple({i["icode"] for i in items}) or ("",)
        doc = q("SELECT licenseno FROM doctor WHERE code=%s", (o["doctor"],))
        return {
            "ovst": o,
            "patient": q("SELECT * FROM patient WHERE hn=%s", (o["hn"],))[0],
            "opdscreen": (q("SELECT * FROM opdscreen WHERE vn=%s", (vn,)) or [None])[0],
            "ovstdiag": q("SELECT * FROM ovstdiag WHERE vn=%s", (vn,)),
            "opitemrece": items,
            "doctor_license": doc[0]["licenseno"] if doc else "",
            "income_std": {r["income"]: r["std_group"] for r in
                           q("SELECT income,std_group FROM income WHERE income IN (%s)"
                             % ",".join(["%s"] * len(incomes)), incomes)},
            "item_name": {r["icode"]: r["name"] for r in
                          q("SELECT icode,name FROM s_drugitems WHERE icode IN (%s)"
                            % ",".join(["%s"] * len(icodes)), icodes)},
        }
    finally:
        c.close()


def make_txid(dt_iso, vn):
    """transactionId คงที่ต่อ visit = hcode-วันเวลา(14)-vn6หลักท้าย -> ย้อนเช็คได้เสมอ"""
    digits = dt_iso.replace("-", "").replace("T", "").replace(":", "")
    return f"{HCODE}-{digits}-{int(str(vn)[-6:] or 0):06d}"


def make_payload(vn, seq=None):  # seq เก็บไว้เพื่อ backward-compat แต่ไม่ใช้แล้ว
    """vn -> FDH payload dict (1 visit ต่อ 1 ไฟล์).  คืน (payload, ยอดรวม)"""
    data = fetch(vn)
    visit, tot = build(data)
    validate(visit, tot)
    payload = {
        "fdhVersion": "3.0.0",
        "generatedDateTime": dt(str(data["ovst"]["vstdate"]), "0:0:0").split("T")[0] + "T00:00:00",
        "hcode": HCODE, "hisName": HIS_NAME, "hisVersion": HIS_VERSION,
        "hospitalName": HOSPITAL_NAME,
        "transactionId": make_txid(visit["encounter"]["opd"]["dateTime"], vn),
        "totalVisits": {"total": 1, "totalUcVisits": 1},
        "data": [visit],
    }
    return payload, tot


def main():
    if "--selfcheck" in sys.argv:
        _selfcheck()
        return
    vn = next((a for a in sys.argv[1:] if not a.startswith("-")), DEFAULT_VN)
    payload, tot = make_payload(vn)
    with open("payload.json", "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    cha = payload["data"][0]["benefits"]["cha"]
    print(f"✅ สร้าง payload.json แล้ว | ยอดรวม {float(tot):.2f} บาท | {len(cha)} หมวด")
    print("⚠️ ตรวจก่อนส่ง: chrgItem (หมวด) ใช้ std_group 16 หมวด, clinic =", CLINIC_CODE)


if __name__ == "__main__":
    main()
