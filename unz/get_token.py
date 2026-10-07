"""ขั้นที่ 2: ขอ JWT token จาก MOPH Account Center (stdlib เท่านั้น)

ใช้:  python get_token.py            # อ่าน .env แล้วขอ token
      python get_token.py --selfcheck  # ทดสอบ logic อ่าน .env โดยไม่ยิงเน็ต
"""
import hashlib
import hmac
import json
import os
import sys
import urllib.error
import urllib.request
from runtime_paths import ENV_PATH

# คอนโซล Windows ดีฟอลต์เป็น cp874 พิมพ์ไทย/emoji ไม่ได้ — บังคับ UTF-8
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

TOKEN_URL = "https://fdh.moph.go.th/token?Action=get_moph_access_token"
# secret กลางของ MOPH IC (ค่าคงที่สาธารณะ) ใช้ทำ HMAC-SHA256 ของรหัสผ่าน
# override ได้ผ่าน FDH_HMAC_SECRET ใน .env ถ้า MOPH ออก secret เฉพาะ รพ. ให้
DEFAULT_HMAC_SECRET = "$$jwt@moph#"
DEFAULT_ENV = str(ENV_PATH)


def load_env(path=DEFAULT_ENV):
    """parse .env แบบง่าย: KEY=VALUE ทีละบรรทัด, ตัด comment และ quote
    ponytail: parser มินิมอล ไม่รองรับ multi-line/escape — พอสำหรับ 3 ค่านี้
    """
    env = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def get_token(env, password_hash, token_url=None):
    body = json.dumps({
        "user": env["FDH_USER"],
        "hospital_code": env["FDH_HOSPITAL_CODE"],
        "password_hash": password_hash,
    }).encode("utf-8")
    req = urllib.request.Request(
        token_url or env.get("FDH_TOKEN_URL") or TOKEN_URL, data=body,
        headers={
            "Content-Type": "application/json",
            # ponytail: Cloudflare เด้ง UA ของ urllib (err 1010) ต้องปลอมเป็น browser
            "User-Agent": "Mozilla/5.0",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        text = resp.read().decode("utf-8").strip()
    # endpoint คืน token เป็นข้อความ JWT ดิบ (ไม่ห่อ JSON) — เผื่ออนาคตห่อ JSON ก็รองรับ
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"access_token": text}


def _selfcheck():
    import tempfile, os
    sample = '# comment\nFDH_USER="u1"\nFDH_HOSPITAL_CODE = 10665 \n\nFDH_PASSWORD_HASH=\'abc\'\n'
    fd, p = tempfile.mkstemp()
    os.write(fd, sample.encode("utf-8")); os.close(fd)
    try:
        env = load_env(p)
        assert env == {"FDH_USER": "u1", "FDH_HOSPITAL_CODE": "10665",
                       "FDH_PASSWORD_HASH": "abc"}, env
    finally:
        os.remove(p)
    print("selfcheck OK")


if __name__ == "__main__":
    if "--selfcheck" in sys.argv:
        _selfcheck()
        sys.exit(0)
    env = load_env()
    for k in ("FDH_USER", "FDH_HOSPITAL_CODE"):
        if not env.get(k):
            sys.exit(f"ยังไม่ได้เติมค่าใน .env: {k}")

    # คำนวณ password_hash = HMAC-SHA256(password, secret)  ยิงครั้งเดียวเท่านั้น
    # (ห้ามไล่ลองหลายแบบ — เซิร์ฟเวอร์ล็อก account 15 นาทีถ้า fail หลายครั้ง)
    if env.get("FDH_PASSWORD_HASH"):
        password_hash = env["FDH_PASSWORD_HASH"]
    elif env.get("FDH_PASSWORD"):
        secret = env.get("FDH_HMAC_SECRET", DEFAULT_HMAC_SECRET)
        # ตัวพิมพ์ใหญ่ให้ตรงกับตัวอย่างที่ผ่านจริงใน Postman (042FC318...)
        password_hash = hmac.new(secret.encode("utf-8"),
                                 env["FDH_PASSWORD"].encode("utf-8"),
                                 hashlib.sha256).hexdigest().upper()
    else:
        sys.exit("ใส่ FDH_PASSWORD (รหัสดิบ) หรือ FDH_PASSWORD_HASH ใน .env")

    try:
        result = get_token(env, password_hash)
    except urllib.error.HTTPError as e:
        sys.exit(f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')}")
    print("\n✅ ขอ token สำเร็จ")
    print(json.dumps(result, ensure_ascii=False, indent=2))
