"""ขั้นที่ 5: ส่ง payload.json เข้า FDH ตามโหมด API ที่เลือก (POST /dataset/import)

ใช้:  python import_fdh.py [payload.json]
ขอ token ใหม่ทุกครั้ง -> POST -> โชว์ผลตอบกลับดิบ ๆ
"""
import json
import sys
import urllib.error
import urllib.request

import get_token
import api_config


def get_access_token(env=None, config=None):
    """ขอ token (ใช้ hash ใน .env ถ้ามี ไม่งั้น hash จาก password)"""
    env = env or get_token.load_env()
    ph = env.get("FDH_PASSWORD_HASH")
    if not ph:
        import hashlib
        import hmac
        secret = env.get("FDH_HMAC_SECRET", get_token.DEFAULT_HMAC_SECRET)
        ph = hmac.new(secret.encode(), env["FDH_PASSWORD"].encode(), hashlib.sha256).hexdigest().upper()
    config = config or api_config.load(env)
    return get_token.get_token(env, ph, token_url=config.token_url)["access_token"]


def send(payload, token, config=None):
    """POST payload (dict หรือ bytes) เข้า FDH import -> (status, text)"""
    body = payload if isinstance(payload, (bytes, bytearray)) else \
        json.dumps(payload, ensure_ascii=False).encode("utf-8")
    config = config or api_config.load()
    req = urllib.request.Request(
        config.dataset_url("import"), data=body, method="POST",
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {token}", "User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


def main():
    path = next((a for a in sys.argv[1:] if not a.startswith("-")), "payload.json")
    env = get_token.load_env()
    config = api_config.load(env)
    token = get_access_token(env=env, config=config)
    print("✅ ได้ token แล้ว ส่ง payload:", path)
    with open(path, "rb") as f:
        st, txt = send(f.read(), token, config=config)
    print(f"\nHTTP {st}")
    print(txt)


if __name__ == "__main__":
    main()
