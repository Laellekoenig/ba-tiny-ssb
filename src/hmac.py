import hashlib


class HMAC:
    """used for computing HMAC signatures using sha256"""

    def __init__(self, key: bytes = b"bad key"):
        self.key = key
        # calc ipad and opad
        self._ipad = self._calc_pad(0x36)
        self._opad = self._calc_pad(0x5c)

    def _calc_pad(self, const: int) -> bytearray:
        """used for calculating the inner and outer pad"""
        n_bytes = len(self.key)

        # now xor with key, byte by byte
        pad = bytearray(n_bytes)
        for i in range(n_bytes):
            pad[i] = self.key[i] ^ const
        return pad

    def get_signature(self, msg: bytes) -> bytes:
        """computes the HMAC signature of the given bytes
        length of output is 32B"""

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
    """returns the HMAC signature of the provided key and bytes
    the signature is padded to 64 bytes for tiny ssb compatibility"""
    hmac = HMAC(key)
    return hmac.get_signature(payload) + bytes(32)
