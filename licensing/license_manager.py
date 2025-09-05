import os, json, base64, datetime, sys
from typing import Tuple, Dict, Any

from nacl.signing import VerifyKey
from nacl.exceptions import BadSignatureError

# === 공개키(Base64) ===
PUBLIC_KEY_B64 = "REPLACE_ME_BASE64_PUBLIC_KEY"

ENV_LICENSE_VAR = "APP_LICENSE"            # 토큰 직접 전달
ENV_LICENSE_FILE_VAR = "APP_LICENSE_FILE"   # 토큰 파일 경로
DEFAULT_FILENAME = "license.dat"
VENDOR_DIRNAME = "OneInsight"
APP_DIRNAME = "UnifiedCrawler"


def _b64url_decode(s: str) -> bytes:
    s = s.replace('-', '+').replace('_', '/')
    pad = 4 - (len(s) % 4)
    if pad and pad < 4:
        s += '=' * pad
    return base64.b64decode(s)


def _b64url_encode(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip('=')


def _parse_license(license_str: str) -> Tuple[Dict[str, Any], bytes]:
    parts = license_str.strip().split('.')
    if len(parts) != 2:
        raise ValueError("잘못된 라이선스 형식")
    payload_b = _b64url_decode(parts[0])
    sig_b = _b64url_decode(parts[1])
    payload = json.loads(payload_b.decode('utf-8'))
    return payload, sig_b


def _candidate_paths() -> list[str]:
    candidates: list[str] = []
    # 실행 파일 근처
    base_dir = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(sys.argv[0])))
    candidates.append(os.path.join(base_dir, DEFAULT_FILENAME))
    # 공용 데이터
    progdata = os.getenv("PROGRAMDATA") or "/usr/local/share"
    common_dir = os.path.join(progdata, VENDOR_DIRNAME, APP_DIRNAME)
    candidates.append(os.path.join(common_dir, DEFAULT_FILENAME))
    # 사용자 홈
    home = os.path.expanduser('~')
    home_dir = os.path.join(home, f".{APP_DIRNAME.lower()}")
    candidates.append(os.path.join(home_dir, DEFAULT_FILENAME))
    return candidates


def _load_from_paths() -> str | None:
    tok = os.environ.get(ENV_LICENSE_VAR)
    if tok:
        return tok.strip()
    file_from_env = os.environ.get(ENV_LICENSE_FILE_VAR)
    if file_from_env and os.path.exists(file_from_env):
        try:
            return open(file_from_env, 'r', encoding='utf-8').read().strip()
        except Exception:
            pass
    for p in _candidate_paths():
        try:
            if os.path.exists(p):
                return open(p, 'r', encoding='utf-8').read().strip()
        except Exception:
            continue
    return None


def verify_license_from_anywhere() -> Tuple[bool, Dict[str, Any] | str]:
    tok = _load_from_paths()
    if not tok:
        return False, "라이선스가 없습니다(환경변수/파일)."
    return verify_license(tok)


def verify_license(license_str: str) -> Tuple[bool, Dict[str, Any] | str]:
    try:
        payload, sig = _parse_license(license_str)
        pubkey = VerifyKey(base64.b64decode(PUBLIC_KEY_B64))
        pubkey.verify(json.dumps(payload, separators=(',',':')).encode('utf-8'), sig)
        exp = payload.get('exp')
        if not exp:
            return False, "만료(exp) 정보가 없습니다."
        try:
            exp_dt = datetime.date.fromisoformat(exp)
        except Exception:
            return False, "만료(exp) 형식 오류(YYYY-MM-DD)."
        if exp_dt < datetime.date.today():
            return False, f"라이선스 만료({exp})"
        return True, payload
    except BadSignatureError:
        return False, "서명 검증 실패"
    except Exception as e:
        return False, f"검증 오류: {e}"


def save_license_to_disk(license_str: str, path: str | None = None):
    """라이선스를 기본 위치 중 하나에 저장"""
    if path is None:
        # 실행파일 근처에 저장
        base_dir = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(sys.argv[0])))
        path = os.path.join(base_dir, DEFAULT_FILENAME)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(license_str.strip())
    except Exception:
        pass
