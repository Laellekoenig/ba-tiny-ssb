import hashlib
from hmac import sign

PKT_TYPE_sha256HMAC = (0).to_bytes(1, "big")


class Packet:
    """used for verifying and decoding raw bytes"""

    prefix = b"tiny-v01"  # len must be 8B
    pkt_type = PKT_TYPE_sha256HMAC
    hash_algo = hashlib.sha256
    sign_algo = sign
    secret = b"bad secret"

    def __init__(self, feed_id: bytes, seq: bytes,
                 prev_mid: bytes, payload: bytes):

        assert len(feed_id) == 32, "feed_id must be 32B"
        assert len(seq) == 4, "sequence number must be 4B"
        assert len(prev_mid) == 20, "previous msg_id must be 20B"
        # make sure that payload is 48 bytes, rejected if too long
        if len(payload) < 48:
            # too short -> append 0s
            missing = 48 - len(payload)
            payload += bytes(missing)
        assert len(payload) == 48, "payload must be 48B"

        self.log_entry_name = self.prefix + feed_id + seq + prev_mid
        self.feed_id = feed_id
        self.seq = seq
        self.prev_mid = prev_mid
        self.payload = payload
        self.dmx = self._calc_dmx()
        self.signature = self._calc_signature()
        self.mid = self._calc_mid()
        self.wire = self._get_wire()

    def __repr__(self):
        s = "packet(\nfeed_id:{},\nseq:{},\n".format(self.feed_id,
                                                     self.seq)
        s += "prev_mid:{},\npayload:{},\ndmx:{}\n".format(self.prev_mid,
                                                          self.payload,
                                                          self.dmx)
        s += "sig:{},\nmid:{},\nwire:{})".format(self.signature,
                                                 self.mid,
                                                 self.wire)
        return s

    def _calc_dmx(self) -> bytes:
        """calculates the demultiplexing field of the packet"""
        hash_algo = self.hash_algo()
        hash_algo.update(self.log_entry_name)
        return hash_algo.digest()[:7]

    def _expand(self) -> bytes:
        """computes the virtual 120B expanded log entry"""
        return self.log_entry_name + self.dmx + self.pkt_type + self.payload

    def _calc_signature(self) -> bytes:
        """calculates the signature of the packet
        for now, HMAC is used"""
        return self.sign_algo(self.secret, self._expand())

    def _get_full(self) -> bytes:
        """computes the virtual 184B full log entry"""
        return self._expand() + self._calc_signature()

    def _calc_mid(self) -> bytes:
        """computes the virtual 20B message id, referenced in next log"""
        hash_algo = self.hash_algo()
        hash_algo.update(self._get_full())
        return hash_algo.digest()[:20]

    def _get_wire(self) -> bytes:
        """returns the 120B wire format of packet
        'missing' info can be inferred by recipient"""
        return self.dmx + self.pkt_type + self.payload + self.signature


def pkt_from_bytes(feed_id: bytes, seq: bytes,
                   prev_mid: bytes, raw_pkt: bytes) -> Packet:
    """creates a packet from the given params and confirms it
    if can't be validated 'None' is returned"""

    assert len(raw_pkt) == 120, "raw packet length must be 120B"
    # dmx = raw_pkt[:7]
    # pkt_type = raw_pkt[7:8]
    payload = raw_pkt[8:56]
    signature = raw_pkt[56:]

    pkt = Packet(feed_id, seq, prev_mid, payload)

    # now confirm packet
    if signature != pkt.signature:
        print("packet not trusted")
        return None
    return pkt


def create_genesis_pkt(feed_id: bytes, payload: bytes):
    assert len(payload) == 48, "payload of must be 48B"
    seq = (1).to_bytes(4, "big")  # seq numbers start at 1
    prev_mid = feed_id[:20]  # tiny ssb convention
    return Packet(feed_id, seq, prev_mid, payload)


def create_succ(prev: Packet, payload: bytes) -> bytes:
    assert len(payload) == 48, "payload of must be 48B"
    seq = int.from_bytes(prev.seq, "big") + 1
    return Packet(prev.feed_id, (seq).to_bytes(4, "big"), prev.mid, payload)
