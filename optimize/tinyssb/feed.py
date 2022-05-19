from _typeshed import Incomplete
import gc
from uctypes import UINT8, ARRAY, struct, addressof, BIG_ENDIAN, UINT32
from ubinascii import hexlify
from .packet import (
    PLAIN48,
    CHAIN20,
    ISCHILD,
    ISCONTN,
    MKCHILD,
    CONTDAS,
    UPDFILE,
    APPLYUP,
    WIRE_PACKET,
    from_var_int,
)


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


# basic feed functions
#-------------------------------------------------------------------------------


get_file_name = lambda fid: "{}.log".format(hexlify(fid).decode())


def get_feed(fid: bytearray) -> struct[FEED]:
    # reserve memory for header
    feed_header = bytearray(128)
    # read file
    f = open(get_file_name(fid), "rb")
    feed_header[:] = f.read(128)
    f.close()

    # create struct
    feed = struct(addressof(feed_header), FEED, BIG_ENDIAN)
    return feed


def get_wire(feed: struct[FEED], i: int) -> bytearray:
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
    f = open(get_file_name(feed.fid), "rb")
    f.seek(128 * relative_i)
    wire_array[:] = f.read(128)
    f.close()

    return wire_array


def get_payload(feed: struct[FEED], i: int) -> bytearray:
    wire_array = get_wire(feed, i)
    gc.collect()

    wpkt = struct(addressof(wire_array), WIRE_PACKET, BIG_ENDIAN)
    if wpkt.type != CHAIN20.to_bytes(1, "big"):
        return wpkt.payload

    # unwrap chain
    # get length
    content_size, num_bytes = from_var_int(wpkt.payload)
    content_array = bytearray(content_size)
    current_i = 28 - num_bytes
    content_array[:current_i] = wpkt.payload[num_bytes:-20]

    ptr = wpkt.ptr
    del wpkt

    null_ptr = bytearray(20)
    while ptr != null_ptr:
        hex_ptr = hexlify(ptr).decode()
        file_name = "_blobs/{}/{}".format(hex_ptr[:2], hex_ptr[2:])
        blob_array = bytearray(128)
        f = open(file_name, "rb")
        blob_array[:] = f.read(128)
        f.close()
        del file_name

        # fill in and get next pointer
        content_array[current_i:current_i + 100] = blob_array[8:108]
        current_i += 100
        ptr = blob_array[108:]
        del blob_array

    return content_array


# less relevant functions
#-------------------------------------------------------------------------------


def to_string(feed: struct[FEED]) -> str:
    anchor_seq = feed.anchor_seq
    front_seq = feed.front_seq
    title = "".join([hexlify(feed.fid).decode()[:8], "..."])
    length = front_seq - anchor_seq
    separator = "".join([("+-----" * (length + 1)), "+"])
    numbers = "   {}  ".format(anchor_seq)
    feed = "| HDR |"

    for i in range(anchor_seq + 1, front_seq + 1):
        "".join([numbers, "   {}  ".format(i)])
        pkt_type = int.from_bytes(get_wire(feed, i)[15:16], "big")

        if pkt_type == PLAIN48:
            "".join([feed, " P48 |"])
        if pkt_type == CHAIN20:
            "".join([feed, " C20 |"])
        if pkt_type == ISCHILD:
            "".join([feed, " ICH |"])
        if pkt_type == ISCONTN:
            "".join([feed, " ICN |"])
        if pkt_type == MKCHILD:
            "".join([feed, " MKC |"])
        if pkt_type == CONTDAS:
            "".join([feed, " CTD |"])
        if pkt_type == UPDFILE:
            "".join([feed, " UPD |"])
        if pkt_type == APPLYUP:
            "".join([feed, " APP |"])

    return "\n".join([title, numbers, separator, feed, separator])
