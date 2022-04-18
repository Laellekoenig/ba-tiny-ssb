import hashlib
import pure25519


def sign_elliptic(key: bytes, payload: bytes) -> bytes:
    """creates a 64B elliptic curve signature of the given payload
    using the secret key
    can be confirmed using the corresponding public key"""
    assert len(key) == 32, "signing key must be 32B"
    skey = pure25519.SigningKey(key)
    return skey.sign(payload)


def verify_elliptic(msg: bytes, signature: bytes, key: bytes) -> bool:
    """attempts to verify the given message and signature
    returns True if successful"""
    assert len(signature) == 64, "signature must be 64B"
    assert len(key) == 32, "key must be 32B"
    vkey = pure25519.VerifyingKey(key)
    try:
        vkey.verify(signature, msg)
        return True
    except Exception:
        return False


class Crypto:
    """
    Used for calculating HMAC signatures using sha256
    and a secret (symmetric) key.
    """

    sha256 = None

    def __init__(self, key: bytes = b"bad key"):
        self._key = key
        # calc ipad and opad
        self._ipad = self._calc_pad(0x36)
        self._opad = self._calc_pad(0x5c)

    def _calc_pad(self, const: int) -> bytearray:
        """"
        Used for calculating inner and outer pad for HMAC.
        """
        n_bytes = len(self._key)

        # now xor with key, byte by byte
        pad = bytearray(n_bytes)
        for i in range(n_bytes):
            pad[i] = self._key[i] ^ const
        return pad

    def get_key(self) -> bytes:
        """
        Returns the current key as bytes.
        Do not access the key directly, since the ipad and opad
        have to be recomputed after the key is changed.
        """
        return self._key

    def update_key(self, key: bytes) -> None:
        """
        Used for changing the key.
        The ipad and opad are recomputed.
        """
        self._key = key
        self._ipad = self._calc_pad(0x36)
        self._opad = self._calc_pad(0x5c)

    def get_signature(self, msg: bytes) -> bytes:
        """
        Computes the HMAC signature of the given bytes.
        Length of the output is 32B.
        """

        # inner digest
        inner = self._ipad + msg
        self.sha256 = hashlib.sha256()
        self.sha256.update(inner)
        h_inner = self.sha256.digest()
        del self.sha256

        # outer digest
        outer = self._opad + h_inner
        self.sha256 = hashlib.sha256()
        self.sha256.update(outer)
        hmac = self.sha256.digest()
        del self.sha256
        return hmac

    def hash(self, msg: bytes) -> bytes:
        self.sha256 = hashlib.sha256()
        self.sha256.update(msg)
        h = self.sha256.digest()
        del self.sha256
        return h

    def sign(self, payload: bytes) -> bytes:
        hmac = self.get_signature(payload)
        return hmac + bytes(32)
