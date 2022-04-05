import hashlib
PFX = b'tinyssb-0.0.1'

class Packet:

    def __init__(self, feed_id, seq, prev):
        self.feed_id = feed_id
        self.seq = seq
        self.prev = prev
        self.log_name = PFX + self.feed_id + self.seq.to_bytes(4,'big') + self.prev
        self.dmx = self._dmx(self.log_name)
        self.type = None
        self.payload = None
        self.signature = None
        self.wire = None
        self.msg_id = None
        self.chain_len = -1
        self.chain_content = b''
        self.chain_nextptr = None # hashptr of next (pending) blob

    def _dmx(self, log_name: bytes) -> bytes:
        return hashlib.sha256(log_name).digest()[:7]

    def _msg_id(self, type, payload: bytes, sign_function) -> bytes:
        return hashlib.sha256(self.log_name + self.wire).digest()[:20]

    def _sign(self, type, payload, sign_function):
        assert len(payload) == 48
        self.type = bytes([type])
        self.payload = payload
        msg = self.dmx + self.type + self.payload
        self.signature = signFct(self.log_name + msg)
        self.wire = msg + self.signature
        self.msg_id = self._msg_id()
 
    