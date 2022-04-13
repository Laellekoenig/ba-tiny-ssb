import hashlib


class HMAC:
    """
    Used for calculating HMAC signatures using sha256
    and a secret (symmetric) key.
    """

    def __init__(self, key: bytes = b"bad key"):
        self.key = key
        # calc ipad and opad
        self._ipad = self._calc_pad(0x36)
        self._opad = self._calc_pad(0x5c)

    def _calc_pad(self, const: int) -> bytearray:
        """"
        Used for calculating inner and outer pad for HMAC.
        """
        n_bytes = len(self.key)

        # now xor with key, byte by byte
        pad = bytearray(n_bytes)
        for i in range(n_bytes):
            pad[i] = self.key[i] ^ const
        return pad

    def get_signature(self, msg: bytes) -> bytes:
        """
        Computes the HMAC signature of the given bytes.
        Length of the output is 32B.
        """

        # inner digest
        inner = self._ipad + msg
        sha = hashlib.sha256()
        sha.update(inner)
        h_inner = sha.digest()

        # outer digest
        outer = self._opad + h_inner
        sha = hashlib.sha256()
        sha.update(outer)
        return sha.digest()


def sign(pkt_instance, key: bytes, payload: bytes) -> bytes:
    """
    Calculates the HMAC signature of the given bytes.
    Uses the given symmetric key.
    The signature is padded to 64B for tiny ssb compatibility.
    Must be called from within a class (e.g. Packet).
    The first argument is the caller class instance.
    """
    hmac = HMAC(key)
    return hmac.get_signature(payload) + bytes(32)
