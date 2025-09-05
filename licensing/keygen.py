# licensing/keygen.py
import base64
from nacl.signing import SigningKey

if __name__ == "__main__":
    sk = SigningKey.generate()
    pk = sk.verify_key
    print("PRIVATE_KEY_B64 =", base64.b64encode(bytes(sk)).decode())
    print("PUBLIC_KEY_B64  =", base64.b64encode(bytes(pk)).decode())
