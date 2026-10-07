"""เมนูเลือกคนไข้ส่ง FDH ตามช่วงวันที่ (OPD สิทธิบัตรทอง UCS)

ใช้:
  python send_menu.py                         # ช่วง = วันนี้ แล้วถามให้เลือก
  python send_menu.py --from 2026-06-01 --to 2026-06-25
  python send_menu.py --from 2026-06-25 --send 1,3      # ส่งเลยไม่ต้องถาม
  python send_menu.py --from 2026-06-25 --send all
  python send_menu.py --from 2026-06-25 --list          # แค่ดูรายชื่อ ไม่ส่ง

อ่าน DB read-only (เลือกคนไข้) แล้ว reuse build_payload + import_fdh ในการส่ง
"""
import datetime
import sys

import build_payload
import get_token
import import_fdh
import api_config


def _arg(name, default=None):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


def list_visits(d_from, d_to, exclude_an=True, exclude_low=True, require_dx=True):
    """คืน list ของ visit OPD UCS ในช่วงวันที่ (read-only)

    ตัวกรองคัดออก (เปิด/ปิดได้):
      exclude_an  : ตัดรายที่มีเลข AN (= IPD นอน รพ.)
      exclude_low : ตัดรายที่ยอดรวม 0 หรือ 50 บาท
      require_dx  : ตัดรายที่ไม่มีวินิจฉัยหลัก (PDX ว่าง) หรือ PDX = U99
    """
    import db
    c = db.connect()
    cond = ["o.vstdate BETWEEN %s AND %s", "pt.hipdata_code='UCS'"]
    if exclude_an:
        cond.append("(o.an IS NULL OR o.an='')")
    if exclude_low:
        cond.append("COALESCE((SELECT SUM(r.sum_price) FROM opitemrece r WHERE r.vn=o.vn),0) "
                    "NOT IN (0,50)")
    if require_dx:
        cond.append("EXISTS (SELECT 1 FROM ovstdiag d WHERE d.vn=o.vn AND d.diagtype='1' "
                    "AND d.icd10<>'' AND d.icd10 NOT LIKE 'U99%%')")  # %% เพราะ pymysql
    sql = """SELECT o.vn, o.an, o.vstdate, o.vsttime, o.hn,
                    p.pname, p.fname, p.lname, pt.name AS ptname,
                    (SELECT SUM(r.sum_price) FROM opitemrece r WHERE r.vn=o.vn) AS tot
             FROM ovst o
             JOIN patient p ON p.hn=o.hn
             JOIN pttype pt ON pt.pttype=o.pttype
             WHERE """ + "\n               AND ".join(cond) + """
             ORDER BY o.vstdate, o.vsttime"""
    try:
        with c.cursor() as cur:
            cur.execute("SET SESSION TRANSACTION READ ONLY")
            cur.execute(sql, (d_from, d_to))
            return cur.fetchall()
    finally:
        c.close()


def list_discharged(d_from, d_to):
    """คืน list ผู้ป่วยใน (IPD) สิทธิบัตรทองที่จำหน่าย (d/c) ในช่วงวันที่ — read-only

    มุมมองวางแผน: ยังไม่ส่ง FDH (IPD ต้องมี mapper แยก)
    """
    import db
    c = db.connect()
    sql = """SELECT i.an, i.hn, i.regdate, i.dchdate, w.name AS wardname,
                    DATEDIFF(i.dchdate, i.regdate) AS los,
                    p.pname, p.fname, p.lname,
                    (SELECT SUM(r.sum_price) FROM opitemrece r WHERE r.an=i.an) AS tot
             FROM ipt i
             JOIN patient p ON p.hn=i.hn
             LEFT JOIN ward w ON w.ward=i.ward
             JOIN pttype pt ON pt.pttype=i.pttype
             WHERE i.dchdate BETWEEN %s AND %s
               AND pt.hipdata_code='UCS'
             ORDER BY i.dchdate, i.an"""
    try:
        with c.cursor() as cur:
            cur.execute("SET SESSION TRANSACTION READ ONLY")
            cur.execute(sql, (d_from, d_to))
            return cur.fetchall()
    finally:
        c.close()


def show(rows, d_from, d_to):
    print(f"\nOPD สิทธิบัตรทอง (UCS) ช่วง {d_from} ถึง {d_to} — พบ {len(rows)} ราย\n")
    print(f"  {'#':>3}  {'วันที่':<10} {'เวลา':<8} {'HN':<9} {'ชื่อ-สกุล':<28} {'ยอด(บาท)':>10}")
    print("  " + "-" * 72)
    for i, r in enumerate(rows, 1):
        name = f"{r['pname']}{r['fname']} {r['lname']}"
        print(f"  {i:>3}  {str(r['vstdate']):<10} {str(r['vsttime']):<8} {r['hn']:<9} "
              f"{name[:28]:<28} {float(r['tot'] or 0):>10.2f}")
    print()


def send_one(row, token, seq, config=None):
    name = f"{row['pname']}{row['fname']} {row['lname']}"
    payload, tot = build_payload.make_payload(row["vn"], seq=seq)
    st, txt = import_fdh.send(payload, token, config=config)
    mark = "✅" if st == 200 and '"success"' in txt else "❌"
    print(f"  {mark} {name} (HN {row['hn']}, ยอด {float(tot):.2f}) -> HTTP {st}: {txt}")
    return st == 200


def main():
    today = datetime.date.today().isoformat()
    d_from = _arg("--from", today)
    d_to = _arg("--to", d_from)
    rows = list_visits(d_from, d_to)
    show(rows, d_from, d_to)
    if not rows or "--list" in sys.argv:
        return

    pick = _arg("--send")
    if pick is None:
        pick = input("เลือกหมายเลขที่จะส่ง (คั่นด้วย , หรือพิมพ์ all, Enter=ยกเลิก): ").strip()
    if not pick:
        print("ยกเลิก ไม่ส่งอะไร")
        return

    chosen = rows if pick.lower() == "all" else \
        [rows[int(n) - 1] for n in pick.split(",") if n.strip().isdigit()
         and 1 <= int(n) <= len(rows)]
    if not chosen:
        print("ไม่มีรายการที่เลือกถูกต้อง")
        return

    config = api_config.load()
    print(f"\nกำลังส่ง {len(chosen)} ราย เข้า FDH {config.environment}...")
    token = import_fdh.get_access_token(config=config)
    ok = sum(send_one(r, token, seq=i, config=config) for i, r in enumerate(chosen, 1))
    print(f"\nเสร็จ: สำเร็จ {ok}/{len(chosen)} ราย")


if __name__ == "__main__":
    main()
