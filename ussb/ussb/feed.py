from .packet import (
    APPLYUP,
    CHAIN20,
    CONTDAS,
    ISCHILD,
    ISCONTN,
    MKCHILD,
    PACKET,
    PKT_PREFIX,
    PLAIN48,
    UPDFILE,
    WIRE_PACKET,
    create_apply_pkt,
    create_chain,
    create_child_pkt,
    create_contn_pkt,
    create_end_pkt,
    create_parent_pkt,
    create_upd_pkt,
    new_packet,
    pkt_from_wire,
)
from .util import listdir, from_var_int
from sys import implementation
from ubinascii import hexlify
from uctypes import (
    ARRAY,
    BIG_ENDIAN,
    UINT32,
    UINT8,
    addressof,
    bytearray_at,
    sizeof,
    struct,
)
from uhashlib import sha256
from uos import mkdir, stat


# helps with debugging in vim
if implementation.name != "micropython":
    from typing import Optional, List, Tuple, Union


# struct definition
FEED = {
    "reserved": (0 | ARRAY, 12 | UINT8),
    "fid": (12 | ARRAY, 32 | UINT8),
    "parent_fid": (44 | ARRAY, 32 | UINT8),
    "parent_seq": 76 | UINT32,
    "anchor_seq": 80 | UINT32,
    "anchor_mid": (84 | ARRAY, 20 | UINT8),
    "front_seq": 104 | UINT32,
    "front_mid": (108 | ARRAY, 20 | UINT8),
}


# helper functions
get_log_fn = lambda fid: "_feeds/{}.log".format(hexlify(fid).decode())
get_header_fn = lambda fid: "_feeds/{}.head".format(hexlify(fid).decode())


def save_header(feed: struct[FEED]) -> None:
    """
    Saves the content of the given feed struct into a .head file with the
    feed ID as file name.
    """
    f = open(get_header_fn(feed.fid), "wb")
    f.write(bytearray_at(addressof(feed), sizeof(FEED)))
    f.close()


def get_feed(fid: bytearray) -> struct[FEED]:
    """
    Creates a feed struct instance from the given feed ID.
    This is done by reading the corresponding .head file.
    Leads to an error if the file does not exist -> only use if feed exists.
    """
    # reserve memory for header
    feed_header = bytearray(128)

    # read file
    f = open(get_header_fn(fid), "rb")
    feed_header[:] = f.read(128)
    f.close()

    # create struct
    feed = struct(addressof(feed_header), FEED, BIG_ENDIAN)
    return feed


def create_feed(
    fid: bytearray,
    trusted_seq: int = 0,
    trusted_mid: Optional[bytearray] = None,
    parent_seq: int = 0,
    parent_fid: bytearray = bytearray(32),
) -> struct[FEED]:
    """
    Creates a new feed instance and saves the .head file.
    """
    if trusted_mid is None:
        trusted_mid = fid[:20]  # tinyssb convention, self-signed

    assert len(fid) == 32
    assert len(trusted_mid) == 20
    assert len(parent_fid) == 32

    # create header
    feed = struct(addressof(bytearray(sizeof(FEED))), FEED, BIG_ENDIAN)
    feed.fid[:] = fid
    feed.parent_fid[:] = parent_fid
    feed.parent_seq = parent_seq
    feed.anchor_seq = trusted_seq
    feed.anchor_mid[:] = trusted_mid
    feed.front_seq = trusted_seq
    feed.front_mid[:] = fid[:20]  # tinyssb convention, self-signed

    save_header(feed)
    return feed


def create_child_feed(
    parent_feed: struct[FEED],
    parent_key: bytearray,
    child_fid: bytearray,
    child_key: bytearray,
) -> struct[FEED]:
    """
    Creates a new child feed from the given parent feed.
    Also saves the .head file of the new child feed.
    """
    parent_seq = (parent_feed.front_seq + 1).to_bytes(4, "big")
    parent_pkt = create_parent_pkt(
        parent_feed.fid,
        parent_seq,
        parent_feed.front_mid,
        child_fid,
        parent_key,
    )

    child_feed = create_feed(
        child_fid, parent_seq=parent_feed.front_seq + 1, parent_fid=parent_feed.fid
    )

    # create child packet
    child_payload = bytearray(48)
    child_payload[:32] = parent_feed.fid
    child_payload[32:36] = parent_seq
    child_payload[36:] = sha256(
        bytearray_at(addressof(parent_pkt.wire[0]), sizeof(WIRE_PACKET))
    ).digest()[:12]

    child_pkt = create_child_pkt(child_fid, child_payload, child_key)

    # append both
    append_packet(child_feed, child_pkt)
    append_packet(parent_feed, parent_pkt)
    return child_feed


def create_contn_feed(
    ending_feed: struct[FEED],
    ending_key: bytearray,
    contn_fid: bytearray,
    contn_key: bytearray,
) -> struct[FEED]:
    """
    Creates a continuation feed from the given (ending) feed.
    Also saves the .head file of the new continuation feed.
    """
    ending_seq = (ending_feed.front_seq + 1).to_bytes(4, "big")
    ending_pkt = create_end_pkt(
        ending_feed.fid,
        ending_seq,
        ending_feed.front_mid,
        contn_fid,
        ending_key,
    )

    cont_feed = create_feed(
        contn_fid, parent_fid=ending_feed.fid, parent_seq=ending_feed.front_seq + 1
    )

    cont_payload = bytearray(48)
    cont_payload[:32] = ending_feed.fid
    cont_payload[32:36] = ending_seq
    cont_payload[36:] = sha256(
        bytearray_at(addressof(ending_pkt.wire[0]), sizeof(WIRE_PACKET))
    ).digest()[:12]

    contn_pkt = create_contn_pkt(contn_fid, cont_payload, contn_key)

    append_packet(cont_feed, contn_pkt)
    append_packet(ending_feed, ending_pkt)
    return cont_feed


def get_wire(feed: struct[FEED], i: int) -> bytearray:
    """
    Returns the (128B) wire packet with the given sequence number of the
    given feed. Also accepts negative indices (-1 => last packet).
    """
    # transform negative indices
    if i < 0:
        i = feed.front_seq + i + 1

    # check if index is valid
    anchor_seq = feed.anchor_seq
    if i > feed.front_seq or i <= anchor_seq:
        raise IndexError

    # get wire packet
    relative_i = i - anchor_seq
    del anchor_seq

    wire_array = bytearray(128)
    f = open(get_log_fn(feed.fid), "rb")
    f.seek(128 * (relative_i - 1))  # -1 because header is in a separate file
    wire_array[:] = f.read(128)
    f.close()

    return wire_array


def get_payload(feed: struct[FEED], i: int) -> bytearray:
    """
    Returns the payload with the given sequence number of the given feed.
    If it is a CHAIN20 packet, the full blob chain is returned.
    """
    # get wire packet
    wire_array = get_wire(feed, i)

    wpkt = struct(addressof(wire_array), WIRE_PACKET, BIG_ENDIAN)
    if wpkt.type != CHAIN20.to_bytes(1, "big"):
        return wpkt.payload

    # TODO: handle more packet types (UPDFILE, APPLYUP, etc)?

    # blob chain -> get full content
    content_size, num_bytes = from_var_int(wpkt.payload)  # get length
    if content_size <= 27:
        # contained in single packet
        return wpkt.payload[1 : 1 + content_size]

    # prepare for reading full blob
    content_array = bytearray(content_size)
    current_i = 28 - num_bytes
    content_array[:current_i] = wpkt.payload[num_bytes:-20]
    ptr = wpkt.payload[-20:]
    del wpkt

    # unwrap chain
    null_ptr = bytearray(20)
    while ptr != null_ptr:
        # search for file
        hex_ptr = hexlify(ptr).decode()
        file_name = "_blobs/{}/{}".format(hex_ptr[:2], hex_ptr[2:])

        # read blob
        blob_array = bytearray(128)
        f = open(file_name, "rb")
        blob_array[:] = f.read(128)
        f.close()
        del file_name

        # get next pointer
        ptr = blob_array[108:]
        if ptr == null_ptr:
            content_array[current_i:] = blob_array[8 : content_size - current_i + 8]
        else:
            content_array[current_i : current_i + 100] = blob_array[8:108]
            current_i += 100
        del blob_array

    return content_array


def get_dependency(feed: struct[FEED], i: int) -> Optional[int]:
    """
    Returns the dependency of a blob (containing an update) with the
    given sequence number in the given feed.
    This only works for correctly formatted file update feeds.
    """
    wire_array = get_wire(feed, i)
    wpkt = struct(addressof(wire_array), WIRE_PACKET, BIG_ENDIAN)

    if wpkt.type != CHAIN20.to_bytes(1, "big"):
        # updates are blobs
        return None

    _, num_bytes = from_var_int(wpkt.payload)
    return int.from_bytes(wpkt.payload[num_bytes : num_bytes + 4], "big")


def append_packet(feed: struct[FEED], pkt: struct[PACKET]) -> None:
    """
    Appends the given packet to the given feed. The signature of the
    packet is not checked. Only meant to be used by the producer of a feed.
    """
    # FIXME: check for CONTDAS packet (feed has ended).

    # append packet to .log file
    f = open(get_log_fn(feed.fid), "ab")
    f.write(bytearray_at(addressof(pkt.wire[0]), sizeof(WIRE_PACKET)))
    f.close()

    # update and save header
    feed.front_mid[:] = pkt.mid
    feed.front_seq += 1
    save_header(feed)


def append_bytes(feed: struct[FEED], payload: bytearray, key: bytearray) -> None:
    """
    Append given payload as a PLAIN48 packet (max 48B) to a given feed.
    The packet is signed with the given key.
    """
    payload_len = len(payload)
    assert payload_len <= 48

    # pad content to 48B if needed
    if payload_len < 48:
        padded_payload = bytearray(48)
        padded_payload[:payload_len] = payload
        del payload
        payload = padded_payload
        del padded_payload

    # create and append packet
    pkt_type = PLAIN48.to_bytes(1, "big")
    seq = (feed.front_seq + 1).to_bytes(4, "big")
    pkt = new_packet(
        feed.fid,
        seq,
        feed.front_mid,
        payload,
        pkt_type,
        key,
    )
    append_packet(feed, pkt)


def append_blob(feed: struct[FEED], payload: bytearray, key: bytearray) -> None:
    """
    Appends the given payload as a blob to the given feed.
    No size limitation other than memory.
    """
    pkt, blobs = create_chain(
        feed.fid, (feed.front_seq + 1).to_bytes(4, "big"), feed.front_mid, payload, key
    )

    # save blob files
    # pointer: a3e26124...
    # saved as: _blobs/a3/e26124...
    ptr = hexlify(pkt.wire[0].payload[-20:]).decode()
    for blob in blobs:
        dir_name = ptr[:2]
        file_name = ptr[2:]
        del ptr

        if dir_name not in listdir("_blobs"):
            mkdir("_blobs/{}".format(dir_name))

        # write blob
        f = open("_blobs/{}/{}".format(dir_name, file_name), "wb")
        f.write(bytearray_at(addressof(blob), sizeof(blob)))
        f.close()

        # get next ptr
        ptr = hexlify(blob.pointer).decode()

    del blobs
    assert ptr == hexlify(bytes(20)).decode()  # null pointer
    # append packet to feed
    append_packet(feed, pkt)


def verify_and_append_bytes(feed: struct[FEED], wpkt: bytearray) -> bool:
    """
    Attempts to verify and append the given wire packet to the given feed.
    Returns True if successful.
    """
    pkt = pkt_from_wire(
        feed.fid, (feed.front_seq + 1).to_bytes(4, "big"), feed.front_mid, wpkt
    )

    if pkt is None:
        print("verification of packet failed")
        return False

    wpkt = bytearray_at(addressof(pkt.wire[0]), sizeof(WIRE_PACKET))
    append_packet(feed, pkt)
    return True


def get_parent(feed: struct[FEED]) -> Optional[bytearray]:
    """
    Returns the feed ID of the given feed's parent feed.
    If the given feed does not have a parent, None is returned.
    """
    if feed.anchor_seq != 0 or feed.front_seq < 1:
        return None
    wire = get_wire(feed, 1)

    # check type
    if wire[15:16] != ISCHILD.to_bytes(1, "big"):
        return None

    # return parent fid
    return wire[16:48]


def get_children(
    feed: struct[FEED], index: bool = False
) -> Union[List[bytearray], List[Tuple[bytearray, int]]]:
    """
    Returns a list of all feed IDs of this feed's children feeds.
    Does not return children of child feeds.
    If the feed does not have children, an empty list is returned.
    ! This function has to iterate over every packet of the given feed.
    """
    children = []
    mk_child = MKCHILD.to_bytes(1, "big")
    for i in range(feed.anchor_seq + 1, feed.front_seq + 1):
        wpkt = get_wire(feed, i)
        if wpkt[15:16] == mk_child:
            if index:
                children.append((wpkt[16:48], i))
            else:
                children.append(wpkt[16:48])

    return children


def get_contn(feed: struct[FEED]) -> Optional[bytearray]:
    """
    Returns the feed ID of the given feed's continuation feed.
    None is returned if it does not exist.
    Only works if the last packet of the feed is the CONTDAS packet.
    """
    if feed.front_seq < 1:
        return None

    wpkt = get_wire(feed, -1)
    if wpkt[15:16] == CONTDAS.to_bytes(1, "big"):
        return wpkt[16:48]

    return None


def get_prev(feed: struct[FEED]) -> Optional[bytearray]:
    """
    Returns the feed ID of the given feed's predecessor feed.
    None is returned if it does not exist.
    """
    if feed.anchor_seq != 0:
        return None

    wpkt = get_wire(feed, 1)
    if wpkt[15:16] == ISCONTN.to_bytes(1, "big"):
        return wpkt[16:48]

    return None


def get_next_dmx(feed: struct[FEED]) -> bytearray:
    """
    Returns the expected DMX value of the next packet.
    """
    dmx = bytearray(64)
    dmx[:8] = PKT_PREFIX
    dmx[8:40] = feed.fid
    dmx[40:44] = (feed.front_seq + 1).to_bytes(4, "big")
    dmx[44:64] = feed.front_mid
    return sha256(dmx).digest()[:7]


def waiting_for_blob(feed: struct[FEED]) -> Optional[bytearray]:
    """
    Returns the pointer to the missing blob.
    If there is no incomplete blob, None is returned.
    """
    if feed.front_seq < 1:
        return None

    # only check front packet
    wpkt = get_wire(feed, -1)
    if wpkt[15:16] != CHAIN20.to_bytes(1, "BIG"):
        return None

    # check if blob chain is complete
    ptr = wpkt[44:64]
    null_ptr = bytearray(20)
    while ptr != null_ptr:
        hex_ptr = hexlify(ptr).decode()
        file_name = "_blobs/{}/{}".format(hex_ptr[:2], hex_ptr[2:])

        # check if file exists
        try:
            blob = bytearray(128)
            f = open(file_name, "rb")
            blob[:] = f.read(128)
            f.close()
        except Exception:
            # does not exist yet, return pointer
            del blob
            return ptr

        ptr[:] = blob[-20:]
        del blob

    return None


def verify_and_append_blob(feed: struct[FEED], blob: bytearray) -> bool:
    """
    Attempts to verify and append the given blob to a given feed.
    Returns True if successful.
    """
    assert len(blob) == 128

    # FIXME: skip check, already done by dmx value when receiving?
    blob_hash = sha256(blob[8:]).digest()[:20]
    if blob_hash != waiting_for_blob(feed):
        # not waiting for this blob
        return False

    # save blob file
    hex_blob = hexlify(blob_hash).decode()

    if hex_blob[:2] not in listdir("_blobs"):
        mkdir("_blobs/{}".format(hex_blob[:2]))

    file_name = "_blobs/{}/{}".format(hex_blob[:2], hex_blob[2:])
    f = open(file_name, "wb")
    f.write(blob)
    f.close()
    return True


def get_want(feed: struct[FEED]) -> bytearray:
    """
    Returns the "want" bytearray for a given feed.
    This is used for requesting packets/blobs from other nodes.
    """
    want_dmx = bytearray(7)
    want_dmx[:] = sha256(feed.fid + b"want").digest()[:7]

    # FIXME: this may be inefficient for long blob chains
    blob_ptr = waiting_for_blob(feed)
    if blob_ptr is None:
        # packet missing
        want = bytearray(43)
        want[:7] = want_dmx
        want[7:39] = feed.fid
        want[39:] = (feed.front_seq + 1).to_bytes(4, "big")
        return want
    else:
        want = bytearray(63)
        want[:7] = want_dmx
        want[7:39] = feed.fid
        want[39:43] = feed.front_seq.to_bytes(4, "big")
        want[43:] = blob_ptr
        return want


def add_upd(
    feed: struct[FEED], file_name: str, key: bytearray, v_number: int = 0
) -> None:
    """
    Adds a packet of type UPDFILE to the given feed, containing the given
    file information.
    """
    seq = bytearray((feed.front_seq + 1).to_bytes(4, "big"))
    pkt = create_upd_pkt(
        feed.fid,
        seq,
        feed.front_mid,
        bytearray(file_name.encode()),
        bytearray(v_number.to_bytes(4, "big")),
        key,
    )
    append_packet(feed, pkt)


def get_upd(feed: struct[FEED]) -> Optional[Tuple[str, int]]:
    """
    Returns the file name and base version number of a given file update feed.
    Only works with a correctly formatted file update feed -> UPD packet must
    be at sequence number 2.
    Format of UPDFILE packet is described in .packet.
    """
    wpkt = get_wire(feed, 2)
    # check type
    if wpkt[15:16] != UPDFILE.to_bytes(1, "big"):
        return None

    # extract info
    fn_len, n_bytes = from_var_int(wpkt[16:64])  # 16:64 -> payload
    offset = 16 + n_bytes
    offset2 = offset + fn_len
    file_name = wpkt[offset:offset2].decode()
    del offset
    v_num = int.from_bytes(wpkt[offset2 : offset2 + 4], "big")
    del offset2

    return file_name, v_num


def add_apply(
    feed: struct[FEED], file_fid: bytearray, v_num: int, key: bytearray
) -> None:
    """
    Adds a packet of type APPLYUP to the given feed (should be version control feed).
    Contains the given information about the update that should be applied.
    """
    seq = (feed.front_seq + 1).to_bytes(4, "big")
    pkt = create_apply_pkt(
        feed.fid,
        seq,
        feed.front_mid,
        file_fid,
        bytearray(v_num.to_bytes(4, "big")),
        key,
    )
    append_packet(feed, pkt)


def get_newest_apply(feed: struct[FEED], file_fid: bytearray) -> Optional[int]:
    """
    Returns the up-to-date version number for a given file update feed ID.
    Iterates over the given feed (should be version control feed), starting from
    the most recent packet, and searches for an APPLYUP packet containing the
    given feed ID.
    """
    applyup = APPLYUP.to_bytes(1, "big")
    for i in range(feed.front_seq, feed.anchor_seq, -1):
        wpkt = get_wire(feed, i)
        if wpkt[15:16] == applyup:
            if wpkt[16:48] == bytes(file_fid):
                return int.from_bytes(wpkt[48:52], "big")
        del wpkt

    return None


def length(feed: struct[FEED]) -> int:
    """
    Returns the length of a given feed.
    This is done using os.stat (1 packet is 128B).
    """
    # FIXME: use feed.front_seq and feed.anchor_seq
    length = (
        stat("".join(["_feeds/", hexlify(bytes(feed.fid)).decode(), ".log"]))[6] // 128
    )
    return length


def to_string(feed: struct[FEED]) -> str:
    """
    Returns a string representation of the given feed.
    Used for displaying feeds in the web GUI.
    """
    title = "".join([hexlify(feed.fid).decode()[:8], "..."])
    length = feed.front_seq - feed.anchor_seq
    separator = "".join([("+-----" * (length + 1)), "+"])
    numbers = "   {}  ".format(feed.anchor_seq)
    feed_str = "| HDR |"

    for i in range(feed.anchor_seq + 1, feed.front_seq + 1):
        if i < 10:
            numbers = "".join([numbers, "   {}  ".format(i)])
        else:
            numbers = "".join([numbers, "  {}  ".format(i)])

        pkt_type = int.from_bytes(get_wire(feed, i)[15:16], "big")

        if pkt_type == PLAIN48:
            feed_str = "".join([feed_str, " P48 |"])
        if pkt_type == CHAIN20:
            feed_str = "".join([feed_str, " C20 |"])
        if pkt_type == ISCHILD:
            feed_str = "".join([feed_str, " ICH |"])
        if pkt_type == ISCONTN:
            feed_str = "".join([feed_str, " ICN |"])
        if pkt_type == MKCHILD:
            feed_str = "".join([feed_str, " MKC |"])
        if pkt_type == CONTDAS:
            feed_str = "".join([feed_str, " CTD |"])
        if pkt_type == UPDFILE:
            feed_str = "".join([feed_str, " UPD |"])
        if pkt_type == APPLYUP:
            feed_str = "".join([feed_str, " APP |"])

    return "\n".join([title, numbers, separator, feed_str, separator])
