# licensing/license_manager.py
import os, json, base64, datetime
from typing import Tuple, Dict, Any

from nacl.signing import VerifyKey
from nacl.exceptions import BadSignatureError

# ======= 공개키 설정 =======
# base64로 인코딩된 32바이트 Ed25519 공개키. (keygen.py로 생성 후 교체)
PUBLIC_KEY_B64 = "REPLACE_ME_BASE64_PUBLIC_KEY"

LICENSE_FILE = "license.txt"  # 프로젝트 루트에 저장/조회

def b64url_decode(s: str) -> bytes:
    s = s.replace('-', '+').replace('_', '/')
    pad = 4 - (len(s) % 4)
    if pad and pad < 4:
        s += '=' * pad
    return base64.b64decode(s)

def b64url_encode(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip('=')

def parse_license(license_str: str) -> Tuple[Dict[str, Any], bytes]:
    """
    license_str: base64url(payload).base64url(signature)
    returns: (payload_dict, signature_bytes)
    """
    try:
        parts = license_str.strip().split(".")
        if len(parts) != 2:
            raise ValueError("잘못된 라이선스 형식")
        payload_b = b64url_decode(parts[0])
        sig_b = b64url_decode(parts[1])
        payload = json.loads(payload_b.decode("utf-8"))
        return payload, sig_b
    except Exception as e:
        raise ValueError(f"라이선스 파싱 실패: {e}")

def verify_license(license_str: str) -> Tuple[bool, Dict[str, Any] | str]:
    """
    성공: (True, payload_dict)
    실패: (False, "에러 메시지")
    """
    try:
        payload, sig = parse_license(license_str)
        pubkey = VerifyKey(base64.b64decode(PUBLIC_KEY_B64))
        # 서명 검증 (detached)
        pubkey.verify(json.dumps(payload, separators=(',',':')).encode("utf-8"), sig)

        # 만료 확인
        exp = payload.get("exp")
        if not exp:
            return False, "만료(exp) 정보가 없습니다."
        try:
            exp_dt = datetime.date.fromisoformat(exp)
        except Exception:
            return False, "만료(exp) 형식이 올바르지 않습니다(YYYY-MM-DD)."
        today = datetime.date.today()
        if exp_dt < today:
            return False, f"라이선스 만료({exp})"

        return True, payload
    except BadSignatureError:
        return False, "서명 검증 실패"
    except Exception as e:
        return False, str(e)

def save_license_to_disk(license_str: str, path: str = LICENSE_FILE):
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(license_str.strip())
    except Exception:
        pass

def load_license_from_disk(path: str = LICENSE_FILE) -> str | None:
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return f.read().strip()
    except Exception:
        pass
    return None
