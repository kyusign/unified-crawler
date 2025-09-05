# licensing/make_license.py
import json, base64, datetime
from nacl.signing import SigningKey
from license_manager import b64url_encode  # 같은 폴더 import (상대 import 단순화)

# >>> 여기 '개발자 PC 전용' 개인키를 붙여넣으세요 (절대 커밋 금지) <<<
PRIVATE_KEY_B64 = "REPLACE_ME_BASE64_PRIVATE_KEY"

def sign_payload(payload: dict) -> str:
    sk = SigningKey(base64.b64decode(PRIVATE_KEY_B64))
    payload_bytes = json.dumps(payload, separators=(',',':')).encode("utf-8")
    sig = sk.sign(payload_bytes).signature  # detached signature
    token = f"{b64url_encode(payload_bytes)}.{b64url_encode(sig)}"
    return token

if __name__ == "__main__":
    # 예시 payload
    payload = {
        "name": "원초적 인사이트",
        "email": "owner@example.com",
        "exp": (datetime.date.today() + datetime.timedelta(days=365)).isoformat(),  # 1년 만료
        "features": ["community", "youtube"]
    }
    token = sign_payload(payload)
    print("LICENSE_TOKEN:\n", token)
