"""ขั้นที่ 3: ดึงข้อมูลดิบของ OPD visit 1 ราย จาก HOSxP (READ-ONLY เท่านั้น)

ใช้:  python query_visit.py [VN]      # ดีฟอลต์ VN = 690625000557

อ่านค่าต่อ DB จาก .env (HOSXP_*) — ยิงแค่ SELECT, มี guard กันเขียน 2 ชั้น:
  1. ทุก query ต้องขึ้นต้นด้วย SELECT/SHOW/DESC เท่านั้น
  2. SET SESSION TRANSACTION READ ONLY (เผื่อ user ไม่ได้เป็น read-only จริง)
ponytail: ใช้ SELECT * ดึงทั้งแถวเพื่อดู "ดิบ ๆ" ก่อน mapping — ยังไม่กรองคอลัมน์
"""
import json
import sys

import get_token  # reuse load_env() + UTF-8 stdout fix

try:
    import pymysql
except ImportError:
    sys.exit("ต้องติดตั้งก่อน:  pip install pymysql")

DEFAULT_VN = "690625000557"
# HOSxP MySQL ดั้งเดิมเก็บภาษาไทยเป็น TIS-620 — override ได้ด้วย HOSXP_CHARSET ใน .env
DEFAULT_CHARSET = "tis620"


def ro_query(cur, sql, args=None):
    """รันได้เฉพาะคำสั่งอ่าน — กัน typo/โค้ดหลุดไปเขียน DB คนไข้จริง"""
    if not sql.lstrip().upper().startswith(("SELECT", "SHOW", "DESC")):
        raise ValueError(f"ปฏิเสธ: query ไม่ใช่คำสั่งอ่าน -> {sql[:40]}")
    cur.execute(sql, args)
    return cur.fetchall()


def main():
    vn = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_VN
    env = get_token.load_env()
    for k in ("HOSXP_HOST", "HOSXP_USER", "HOSXP_PASSWORD", "HOSXP_DB"):
        if not env.get(k):
            sys.exit(f"ยังไม่ได้เติมค่าใน .env: {k}")

    conn = pymysql.connect(
        host=env["HOSXP_HOST"],
        port=int(env.get("HOSXP_PORT") or 3306),
        user=env["HOSXP_USER"],
        password=env["HOSXP_PASSWORD"],
        database=env["HOSXP_DB"],
        charset=env.get("HOSXP_CHARSET") or DEFAULT_CHARSET,
        cursorclass=pymysql.cursors.DictCursor,
        connect_timeout=15,
    )
    out = {"vn": vn}
    try:
        with conn.cursor() as cur:
            cur.execute("SET SESSION TRANSACTION READ ONLY")

            ovst = ro_query(cur, "SELECT * FROM ovst WHERE vn=%s", (vn,))
            out["ovst"] = ovst
            if not ovst:
                sys.exit(f"ไม่พบ visit vn={vn} ในตาราง ovst")
            hn = ovst[0].get("hn")

            out["patient"] = ro_query(cur, "SELECT * FROM patient WHERE hn=%s", (hn,))
            out["ovstdiag"] = ro_query(cur, "SELECT * FROM ovstdiag WHERE vn=%s", (vn,))
            out["opdscreen"] = ro_query(cur, "SELECT * FROM opdscreen WHERE vn=%s", (vn,))
            out["opitemrece"] = ro_query(cur, "SELECT * FROM opitemrece WHERE vn=%s", (vn,))
            # สิทธิการรักษาของ visit นี้ (เลข pttype จาก ovst)
            pttype = ovst[0].get("pttype")
            if pttype is not None:
                out["pttype"] = ro_query(cur, "SELECT * FROM pttype WHERE pttype=%s", (pttype,))
    finally:
        conn.close()

    # default=str กัน date/Decimal serialize ไม่ได้
    print(json.dumps(out, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
