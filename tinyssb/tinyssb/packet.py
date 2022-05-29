import hashlib
import sys
from .crypto import sign_elliptic
from .crypto import verify_elliptic
from .ssb_util import to_var_int

# non-micropython import
if sys.implementation.name != "micropython":
    # Optional type annotations are ignored in micropython
    from typing import Optional
    from typing import List
    from typing import Tuple


class PacketType:
    """
    Enum containing different packet types
    (as defined in tiny-ssb protocol).
    """
    plain48 = bytes([0x00])  # sha256 HMAC signature, signle packet with 48B
    chain20 = bytes([0x01])  # sha256 HMAC signature, start of hash sidechain
    ischild = bytes([0x02])  # metafeed information, only in genesis block
    iscontn = bytes([0x03])  # metafeed information, only in genesis block
    mkchild = bytes([0x04])  # metafeed information
    contdas = bytes([0x05])  # metafeed information
    acknldg = bytes([0x06])  # proof of having some fid:seq:sig entry
    types = [plain48, chain20, ischild, iscontn, mkchild, contdas, acknldg]

    @classmethod
    def is_type(cls, t: bytes) -> bool:
        """
        Returns True if there exists a packet type with the same
        number as the given int.
        """
        return t in cls.types


class Blob:
    """
    Simple class for handling blob information.
    Not used for first blob entry (Packet).
    Uses sha256 for generating pointers to next blob.
    """
    def __init__(self, payload: bytes, ptr: bytes):
        self.payload = payload
        self.ptr = ptr
        self.wire = payload + ptr
        self.signature = hashlib.sha256(self.wire).digest()[:20]


class Packet:
    """
    As defined in the tiny sbb protocol.
    Contains physical and virtual information.
    The maximum payload size of a packet is 48B.
    Uses ed25519 for signing and verifying Packets.
    """
    prefix = b"tiny-v01"  # length must be 8B

    def __init__(self,
                 fid: bytes,
                 seq: bytes,
                 prev_mid: bytes,
                 payload: bytes = bytes(48),
                 pkt_type: bytes = PacketType.plain48,  # default
                 skey: Optional[bytes] = None):

        # check arguments
        assert len(fid) == 32, "feed ID must be 32B"
        assert len(seq) == 4, "sequence number must be 4B"
        assert len(prev_mid) == 20, "previous msg_id must be 20B"
        assert (skey is None or
                len(skey) == 32), "skey must be 32B or None"

        # make sure that payload is 48 bytes, rejected if too long
        if len(payload) < 48:
            # too short -> append 0s
            missing = 48 - len(payload)
            payload += bytes(missing)
        assert len(payload) == 48, "payload must be 48B"

        # build packet
        self.block_name = self.prefix + fid + seq + prev_mid
        self.fid = fid
        self.seq = seq
        self.prev_mid = prev_mid
        self.payload = payload
        self.pkt_type = pkt_type
        self.skey = skey
        self.dmx = self._calc_dmx()

        # sign, if possible
        if self.skey is None:
            self.signature = None
            self.mid = None
            self.wire = None
        else:
            self.signature = self._calc_signature()
            self.mid = self._calc_mid()
            self.wire = self._get_wire()

    def __repr__(self):
        s = "Packet\n"
        s += "------\n"
        s += "fid:\t{}\n".format(self.fid)
        s += "seq:\t{}\n".format(self.seq)
        s += "prev_mid:\t{}\n".format(self.prev_mid)
        s += "payload:\t{}\n".format(self.payload)
        s += "type:\t{}\n".format(self.pkt_type)
        s += "mid:\t{}\n".format(self.mid)
        s += "signature:\t{}".format(self.signature)
        return s

    def _calc_dmx(self) -> bytes:
        """
        Calculates the demultiplexing field of the packet.
        """
        return hashlib.sha256(self.block_name).digest()[:7]

    def next_dmx(self) -> bytes:
        """
        Predicts the next packet's dmx value.
        """
        assert self.mid is not None, "sign packet first"

        next_seq = int.from_bytes(self.seq, "big") + 1
        next = self.prefix + self.fid + next_seq.to_bytes(4, "big") + self.mid
        return hashlib.sha256(next).digest()[:7]

    def _expand(self) -> bytes:
        """
        Computes the 128B expanded block containing 'virtual' information.
        """
        return self.block_name + self.dmx + self.pkt_type + self.payload

    def _calc_signature(self) -> bytes:
        """
        Computes the signature of the packet using the ed25519 algorithm..
        """
        assert self.skey is not None, "key needed for signing"
        return sign_elliptic(self.skey, self._expand())

    def _get_full(self) -> bytes:
        """
        Computes the full 184B block.
        Consists of the expanded block and
        the signature of the packet.
        """
        if self.signature is not None:
            # signature already calculated
            return self._expand() + self.signature
        return self._expand() + self._calc_signature()

    def _calc_mid(self) -> bytes:
        """
        Computes the 20B message ID of the packet.
        This message ID is referenced in the next packet.
        """
        return hashlib.sha256(self._get_full()).digest()[:20]

    def _get_wire(self) -> bytes:
        """
        Returns the 120B 'raw' wire format of the packet.
        The missing 'virtual' information can be inferred by
        the recipient using prior packets.
        """
        assert self.signature is not None, "sign packet first"
        return self.dmx + self.pkt_type + self.payload + self.signature

    def sign(self, skey: bytes = bytes(32)) -> None:
        """Calculates the signature of the Packet and all the related fields
        using the given signing key.
        For testing, the default key is 32 0s."""
        assert len(skey) == 32, "skey must be 32B"
        self.skey = skey
        self.signature = self._calc_signature()
        self.mid = self._calc_mid()
        self.wire = self._get_wire()


def pkt_from_bytes(fid: bytes,
                   seq: bytes,
                   prev_mid: bytes,
                   pkt_wire: bytes) -> Optional[Packet]:
    """
    Creates a Packet instance from the given feed ID, sequence number
    previous message ID and wire bytes.
    Also validates the packet.
    If the signatures do not match, 'None' is returned.
    """
    assert len(pkt_wire) == 120, "length of packet wire format must be 120B"
    assert len(fid) == 32, "feed id must be 32B"

    # dmx = raw_pkt[:7]
    pkt_type = pkt_wire[7:8]
    payload = pkt_wire[8:56]
    signature = pkt_wire[56:]

    # create unsigned Packet
    pkt = Packet(fid, seq, prev_mid, payload, pkt_type=pkt_type)

    # use fid as verification key
    if verify_elliptic(pkt._expand(), signature, fid):
        # verification successful
        # fill-in signature and calculate missing info
        pkt.signature = signature
        pkt.mid = pkt._calc_mid()
        pkt.wire = pkt_wire
        return pkt
    else:
        print("packet not trusted")
        return None


def create_genesis_pkt(fid: bytes, payload: bytes, skey: bytes) -> Packet:
    """
    Creates and returns a 'self-signed' Packet instance
    with sequence number 1.
    Also contains a payload of max. 48B.
    Used when creating new feeds.
    """
    seq = (1).to_bytes(4, "big")  # seq numbers start at 1
    prev_mid = fid[:20]  # tiny ssb convention
    return Packet(fid, seq, prev_mid, payload, skey=skey)


def create_parent_pkt(fid: bytes,
                      seq: bytes,
                      prev_mid: bytes,
                      child_fid: bytes,
                      skey: bytes) -> Packet:
    """
    Creates and returns a Packet instance of type 'mkchild'.
    Is used in parent feed, to refer to child feed.
    No payload can be attached to this packet,
    as it contains information about the child feed.
    """
    # TODO: add more info (time stamp?)
    return Packet(fid, seq, prev_mid, payload=child_fid,
                  pkt_type=PacketType.mkchild, skey=skey)


def create_child_pkt(fid: bytes, payload: bytes, skey: bytes) -> Packet:
    """
    Creates and returns the first packet of a new child feed.
    Starts with sequence number 1 and has packet type 'ischild'.
    """
    seq = (1).to_bytes(4, "big")
    prev_mid = fid[:20]
    return Packet(fid, seq, prev_mid, payload,
                  pkt_type=PacketType.ischild, skey=skey)


def create_end_pkt(fid: bytes,
                   seq: bytes,
                   prev_mid: bytes,
                   contn_fid: bytes,
                   skey: bytes) -> Packet:
    """
    Creates and returns the last packet of a feed.
    Contains information of the continuing feed.
    Has packet type 'contdas'.
    """
    # TODO: add more info (time stamp?)
    return Packet(fid, seq, prev_mid, payload=contn_fid,
                  pkt_type=PacketType.contdas, skey=skey)


def create_contn_pkt(fid: bytes, payload: bytes, skey: bytes) -> Packet:
    """
    Creates and returns the first packet of a continuation feed.
    Starts at sequence number 1 and has packet type 'iscontn'.
    """
    seq = (1).to_bytes(4, "big")
    prev_mid = fid[:20]
    return Packet(fid, seq, prev_mid, payload,
                  pkt_type=PacketType.iscontn, skey=skey)


def create_succ(prev: Packet, payload: bytes, skey: bytes) -> Packet:
    """
    Creates and returns the successor of the given packet,
    containing the given payload.
    """
    assert prev.mid is not None, "previous packet must be signed"
    seq = int.from_bytes(prev.seq, "big") + 1
    return Packet(prev.fid, (seq).to_bytes(4, "big"),
                  prev.mid, payload, skey=skey)


def create_chain(fid: bytes, seq: bytes, prev_mid: bytes,
                 content: bytes, skey: bytes) -> Tuple[Packet, List[Blob]]:
    """
    Creates a blob chain, containing the given bytes.
    The blob is returned as a tuple, containing the header of the blob
    as a packet and a list containing Blob instances.
    Blob instances can easily be saved as bytes by using blob.wire.
    The blob list is empty if the content fits into the blob header.
    """
    chain = []
    # get size as VarInt and prepend to content
    content = to_var_int(len(content)) + content

    # check if content fits into single blob
    num_fill = 28 - len(content)  # how many bytes left to fill content
    if num_fill >= 0:
        # only one blob -> null pointer at end
        header = content + bytes(num_fill)
        ptr = bytes(20)

    else:
        # pad message -> divisible by 100
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
    pkt = Packet(fid, seq, prev_mid, payload,
                 pkt_type=PacketType.chain20, skey=skey)

    chain.reverse()
    return (pkt, chain)
