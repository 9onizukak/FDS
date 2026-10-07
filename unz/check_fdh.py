"""ขั้นที่ 6: ตรวจผลหลัง import ด้วย check_count / get_data ตามโหมด API ที่เลือก

ใช้:  python check_fdh.py
ยังไม่รู้ body ที่ endpoint ต้องการแน่ชัด -> ลองหลายแบบแล้วโชว์ผลดิบให้เห็นว่าตัวไหนผ่าน
"""
import json
import urllib.error
import urllib.request

import get_token
import api_config

_ENV = get_token.load_env()
HCODE = _ENV.get("FDH_HOSPITAL_CODE", "10731")
TXID = f"{HCODE}-20260625000557-000001"
DATE = "2026-06-25"


def post(url, token, body):
    req = urllib.request.Request(
        url, data=json.dumps(body).encode("utf-8"), method="POST",
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {token}", "User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


def _records(txt):
    """แกะ list เรคคอร์ดออกจาก response ไม่ว่าจะห่อแบบไหน
    รองรับ: list ตรง ๆ / {data:[...]} / [{hcode,data:[...]}] / ผสมกัน"""
    d = json.loads(txt)
    if isinstance(d, dict):                 # {message,status,data:[...]}
        d = d.get("data", [])
    if not isinstance(d, list):
        return []
    recs = []
    for item in d:
        if isinstance(item, dict) and isinstance(item.get("data"), list):
            recs.extend(item["data"])       # [{hcode,data:[...]}]
        else:
            recs.append(item)
    return recs


def sent_seqs(token, hcode=HCODE, config=None):
    """ดึง get_data ทั้ง hcode แล้วคืน set ของ seq (=vn) ที่ FDH เก็บไว้แล้ว
    (get_data กรองแค่ hcode ไม่กรอง transactionId จึงเทียบที่ vn เอง)
    คืน None ถ้าเรียก/parse ไม่สำเร็จ"""
    try:
        config = config or api_config.load()
        st, txt = post(config.dataset_url("get_data"), token, {"hcode": hcode})
        if st != 200:
            return None
        seqs = set()
        for r in _records(txt):
            try:
                seqs.add(r["encounter"]["opd"]["seq"])
            except (KeyError, TypeError):
                pass
        return seqs
    except Exception:
        return None


def main():
    env = get_token.load_env()
    config = api_config.load(env)
    ph = env.get("FDH_PASSWORD_HASH")
    token = get_token.get_token(env, ph)["access_token"]
    print("✅ ได้ token แล้ว\n")

    # เดา body หลายแบบ — เลิกลองทันทีที่เจอแบบที่ได้ status 200
    bodies = [
        {"hcode": HCODE, "transactionId": TXID},
        {"transactionId": TXID},
        {"hcode": HCODE, "dateProcess": DATE},
        {"hcode": HCODE, "date": DATE},
        {"hcode": HCODE},
    ]
    for name in ("check_count", "get_data"):
        url = config.dataset_url(name)
        print(f"==================== {name} ====================")
        for b in bodies:
            st, txt = post(url, token, b)
            print(f"body={json.dumps(b, ensure_ascii=False)}\n  -> HTTP {st}: {txt[:300]}")
            if st == 200:
                print("  ^ ใช้ได้")
                break
        print()


if __name__ == "__main__":
    main()
