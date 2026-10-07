"""ต่อ HOSxP (MariaDB) แบบ read-only + decode ทนทาน

HOSxP เก็บไทยเป็น tis620 แต่บางเรคคอร์ดมี byte แปลก (0xa0, 0xff จากการ copy
ข้อความจาก Word/เว็บ) ที่ codec tis620/cp874 ของ Python decode ไม่ได้แล้ว crash
ทั้ง query -> ลงทะเบียน codec 'hosxp_lenient' (cp874 + errors=replace) byte แปลก
กลายเป็น � แทนที่จะพัง
ponytail: byte เสียกลายเป็น � = ยอมเสียอักขระไม่กี่ตัว แลกกับส่งได้ทั้งราย
"""
import codecs

import get_token


def _lenient(name):
    if name.lower() != "hosxp_lenient":
        return None
    base = codecs.lookup("cp874")
    return codecs.CodecInfo(name="hosxp_lenient", encode=base.encode,
                            decode=lambda b, errors="strict": base.decode(b, "replace"))


codecs.register(_lenient)


def connect():
    """คืน pymysql connection (DictCursor) ที่ decode ทนทาน — อ่านอย่างเดียว"""
    import pymysql
    env = get_token.load_env()
    c = pymysql.connect(host=env["HOSXP_HOST"], port=int(env.get("HOSXP_PORT") or 3306),
                        user=env["HOSXP_USER"], password=env["HOSXP_PASSWORD"],
                        database=env["HOSXP_DB"], charset=env.get("HOSXP_CHARSET") or "tis620",
                        cursorclass=pymysql.cursors.DictCursor, connect_timeout=15)
    c.encoding = "hosxp_lenient"
    return c
