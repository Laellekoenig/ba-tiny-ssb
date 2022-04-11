import hashlib
from hmac import sign
from ssb_util import to_var_int


class PacketType:
    """enum for packet types"""

    plain48 = bytes([0x00])  # sha256 HMAC signature, signle packet with 48B
    chain20 = bytes([0x01])  # sha256 HMAC signature, start of hash sidechain
    ischild = bytes([0x02])  # metafeed information, only in genesis block
    iscontn = bytes([0x03])  # metafeed information, only in genesis block
    mkchild = bytes([0x04])  # metafeed information
    contdas = bytes([0x05])  # metafeed information


class Blob:
    """simple class for containing blob information
    not used for first blob entry"""

    def __init__(self, payload: bytes, ptr: bytes):
        self.payload = payload
        self.ptr = ptr
        self.wire = payload + ptr
        self.signature = Packet.hash_algo(self.wire).digest()[:20]


class Packet:
    """used for verifying and decoding raw bytes"""

    prefix = b"tiny-v01"  # len must be 8B
    hash_algo = hashlib.sha256
    sign_algo = sign
    secret = b"bad secret"

    def __init__(self, feed_id: bytes, seq: bytes,
                 prev_mid: bytes, payload: bytes = bytes(48),
                 pkt_type: int = PacketType.plain48):

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
        self.pkt_type = pkt_type
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

    def next_dmx(self) -> bytes:
        """predicts the next packet's dmx"""
        next = self.fid + (self.seq + 1).to_bytes(4, "big") + self.mid
        return self.hash_algo(next).digest()[:20]

    def _expand(self) -> bytes:
        """computes the virtual 120B expanded log entry"""
        return self.log_entry_name + self.dmx + self.pkt_type + self.payload

    def _calc_signature(self) -> bytes:
        """calculates the signature of the packet
        for now, HMAC is used, can be swapped out thorugh Packet.sign_algo"""
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
    pkt_type = raw_pkt[7:8]
    payload = raw_pkt[8:56]
    signature = raw_pkt[56:]

    pkt = Packet(feed_id, seq, prev_mid, payload, pkt_type=pkt_type)

    # now confirm packet
    if signature != pkt.signature:
        print("packet not trusted")
        return None
    return pkt


def create_genesis_pkt(feed_id: bytes, payload: bytes) -> Packet:
    """creates a 'self-signed' packet with sequence number 1"""
    seq = (1).to_bytes(4, "big")  # seq numbers start at 1
    prev_mid = feed_id[:20]  # tiny ssb convention
    return Packet(feed_id, seq, prev_mid, payload)


def create_parent_pkt(feed_id: bytes, seq: bytes,
                      prev_mid: bytes, child_fid: bytes) -> Packet:
    """creates a parent packet for given information"""
    return Packet(feed_id, seq, prev_mid,
                  payload=child_fid, pkt_type=PacketType.mkchild)


def create_child_pkt(feed_id: bytes, payload: bytes) -> Packet:
    """creates the first packet of a child feed
    similar to regular genesis block, pkt type different"""
    seq = (1).to_bytes(4, "big")
    prev_mid = feed_id[:20]
    return Packet(feed_id, seq, prev_mid,
                  payload, pkt_type=PacketType.ischild)


def create_succ(prev: Packet, payload: bytes) -> Packet:
    """creates successor packet of provided packet containing given payload"""
    seq = int.from_bytes(prev.seq, "big") + 1
    return Packet(prev.feed_id, (seq).to_bytes(4, "big"), prev.mid, payload)


def make_chain(feed_id: bytes, seq: bytes, prev_mid: bytes,
               content: bytes) -> (Packet, [Blob]):
    """creates a blob chain for the given content and feed info
    returns a tuple containing the first blob (as a packet)
    and a list containing Blob instances"""
    chain = []
    # get size as var int and prepend to content
    size = to_var_int(len(content))
    content = size + content

    # check if content fits into single blob
    num_fill = 28 - len(content)  # how many bytes left to fill content
    if num_fill >= 0:
        # only one blob -> null pointer at end
        payload = content + bytes(num_fill)
        header = payload
        ptr = bytes(20)
    else:
        # pad msg -> divisible by 100
        header = content[:28]
        content = content[28:]
        pad = 100 - len(content) % 100
        content += bytes(pad)
        # start with last pkt
        ptr = bytes(20)
        while len(content) != 0:
            blob = Blob(content[-100:], ptr)
            chain.append(blob)
            # get next pointer
            ptr = blob.signature
            # cut content
            content = content[:-100]

    # create first pkt
    payload = header + ptr
    assert len(payload) == 48, "blob header must be 48B"
    pkt = Packet(feed_id, seq, prev_mid,
                 payload, pkt_type=PacketType.chain20)

    chain.reverse()
    return (pkt, chain)
