from .feed import (
    FEED,
    append_blob,
    append_bytes,
    create_feed,
    get_children,
    get_feed,
    get_next_dmx,
    get_parent,
    get_want,
    get_wire,
    to_string,
    verify_and_append_blob,
    verify_and_append_bytes,
    waiting_for_blob,
)
from .packet import CONTDAS, MKCHILD, WIRE_PACKET
from .util import listdir
from _thread import allocate_lock
from json import dumps, loads
from os import mkdir
from pure25519 import create_keypair
from sys import implementation
from ubinascii import unhexlify, hexlify
from uctypes import struct, addressof, BIG_ENDIAN
from uhashlib import sha256


# helps debugging in vim
if implementation.name != "micropython":
    from typing import Dict, Tuple, List, Callable, Optional, Union


class FeedManager:

    __slots__ = (
        "keys",
        "fids",
        "dmx_lock",
        "dmx_table",
        "_callback",
    )

    def __init__(self) -> None:
        self.keys = {}
        self._create_dirs()
        self._load_config()
        self.fids = self.listfids()

        # dmx and callbacks
        self.dmx_lock = allocate_lock()
        self.dmx_table = {}
        self._fill_dmx()
        self._callback = {}

    def _create_dirs(self) -> None:
        feeds = "_feeds"
        blobs = "_blobs"
        if feeds not in listdir():
            mkdir(feeds)
        del feeds

        if blobs not in listdir():
            mkdir(blobs)
        del blobs

    def _save_config(self) -> None:
        f = open("fm_config.json", "w")
        f.write(
            dumps(
                {hexlify(k).decode(): hexlify(v).decode() for k, v in self.keys.items()}
            )
        )
        f.close()

    def _load_config(self) -> None:
        file_name = "fm_config.json"
        if file_name not in listdir():
            return

        f = open(file_name)
        str_dict = loads(f.read())
        self.keys = {
            unhexlify(k.encode()): unhexlify(v.encode()) for k, v in str_dict.items()
        }
        f.close()

    def update_keys(self, keys: Dict[bytes, bytes]) -> None:
        self.keys = keys
        self._save_config()

    def generate_keypair(self, save_keys: bool = True) -> Tuple[bytearray, bytearray]:
        key, _ = create_keypair()
        skey = key.sk_s[:32]
        vkey = key.vk_s
        del key
        if save_keys:
            self.keys[vkey] = skey
            self._save_config()
        return bytearray(skey), bytearray(vkey)

    def listfids(self) -> List[bytearray]:
        is_feed = lambda fn: fn.endswith(".head")
        fn2bytes = lambda fn: bytearray(unhexlify(fn[:-5].encode()))
        return list(map(fn2bytes, list(filter(is_feed, listdir("_feeds")))))

    def __str__(self) -> str:
        # not very optimized for pycom
        string_builder = []
        for fid in self.fids:
            feed = get_feed(fid)
            if get_parent(feed):
                continue
            else:
                string_builder.append(to_string(feed))

            # add children below
            children = [(x, y, 0) for x, y in get_children(feed, index=True)]
            while children:
                child, index, offset = children.pop(0)
                assert type(child) is bytearray
                child_feed = get_feed(child)
                child_str = to_string(child_feed)

                # adjust padding
                padding_len = index - feed.anchor_seq + offset
                padding = "      " * padding_len
                child_str = "\n".join(
                    ["".join([padding, s]) for s in child_str.split("\n")]
                )
                string_builder.append(child_str)

                # check for child of child
                child_children = get_children(child_feed, index=True)
                del child_feed
                child_children = [(x, y, padding_len) for x, y in child_children]
                del padding_len
                children = child_children + children

        return "\n".join(string_builder)

    def __len__(self):
        return len(self.fids)

    def __getitem__(self, i: int) -> bytearray:
        return self.fids[i]

    def _fill_dmx(self) -> None:
        with self.dmx_lock:
            for fid in self.fids:
                feed = get_feed(fid)
                want = get_want(feed)
                self.dmx_table[bytes(want)] = (self.handle_want, fid)

                blob_ptr = waiting_for_blob(feed)
                if blob_ptr:
                    self.dmx_table[bytes(blob_ptr)] = (self.handle_blob, fid)
                else:
                    self.dmx_table[bytes(get_next_dmx(feed))] = (
                        self.handle_packet,
                        fid,
                    )

    def get_key(self, fid: bytearray) -> Optional[bytearray]:
        b_fid = bytes(fid)
        with self.dmx_lock:
            if b_fid not in self.keys:
                return None
            return self.keys[b_fid]

    def consult_dmx(
        self, msg: bytearray
    ) -> Optional[Tuple[Callable[[bytearray, bytearray], None], bytearray]]:
        b_msg = bytes(msg)
        with self.dmx_lock:
            if b_msg not in self.dmx_table:
                return None
            return self.dmx_table[b_msg]

    def handle_want(self, fid: bytearray, request: bytearray) -> Optional[bytearray]:
        req_feed = get_feed(fid)
        req_seq = int.from_bytes(request[39:43], "big")
        # check seq number
        if req_feed.front_seq < req_seq:
            return None

        req_wire = bytearray(128)
        if len(request) == 43:
            # packet
            req_wire[:] = get_wire(req_feed, req_seq)
        else:
            # blob
            blob_ptr = request[-20:]
            try:
                f = open("_blobs/{}".format(hexlify(blob_ptr).decode()), "rb")
                req_wire[:] = f.read(128)
                f.close()
            except Exception:
                return None  # blob not found

        return req_wire

    def handle_packet(self, fid: bytearray, wire: bytearray) -> None:
        feed = get_feed(fid)
        wpkt = struct(addressof(wire), WIRE_PACKET, BIG_ENDIAN)
        if not verify_and_append_bytes(feed, wire):
            return

        next_dmx = get_next_dmx(feed)

        blob_ptr = waiting_for_blob(feed)
        if next_dmx == wpkt.dmx and blob_ptr is None:
            # nothing was appended
            return None

        # update dmx value
        with self.dmx_lock:
            del self.dmx_table[wpkt.dmx]
            if blob_ptr is None:
                self.dmx_table[next_dmx] = self.handle_packet, fid
            else:
                self.dmx_table[blob_ptr] = self.handle_blob, fid
                return

        # check for continuation or child feed
        front_wire = get_wire(feed, -1)
        if front_wire[15:16] in [
            CONTDAS.to_bytes(1, "big"),
            MKCHILD.to_bytes(1, "big"),
        ]:
            create_feed(front_wire[16:48], parent_seq=feed.front_seq, parent_fid=fid)

        # callbacks
        if fid in self._callback:
            for function in self._callback[fid]:
                function(fid)

    def handle_blob(self, fid: bytearray, blob: bytearray) -> None:
        feed = get_feed(fid)

        if not verify_and_append_blob(feed, blob):
            return

        signature = sha256(blob[8:]).digest()[:20]

        with self.dmx_lock:
            del self.dmx_table[signature]

        next_ptr = waiting_for_blob(feed)
        if not next_ptr:
            with self.dmx_lock:
                self.dmx_table[get_next_dmx(feed)] = self.handle_packet, fid

                if fid in self._callback:
                    for function in self._callback[fid]:
                        function(fid)

                return

        with self.dmx_lock:
            self.dmx_table[next_ptr] = self.handle_blob, fid

    def register_callback(self, fid: bytearray, function) -> None:
        b_fid = bytes(fid)
        if b_fid not in self._callback:
            self._callback[b_fid] = [function]
        else:
            self._callback[b_fid] = (self._callback[b_fid]).append(function)

    def remove_callback(self, fid: bytearray, function) -> None:
        b_fid = bytes(fid)
        if b_fid not in self._callback:
            return

        functions = self._callback[b_fid]
        if function in functions:
            functions.remove(function)
        self._callback[b_fid] = functions

    def append_to_feed(
        self, feed: Union[bytearray, struct[FEED]], payload: bytearray
    ) -> bool:
        try:
            if type(feed) is bytearray:
                feed = get_feed(feed)
            append_bytes(feed, payload, self.keys[bytes(feed.fid)])
            return True
        except Exception:
            print("key not in dictionary")
            return False

    def append_blob_to_feed(
        self, feed: Union[bytearray, struct[FEED]], payload: bytearray
    ) -> bool:
        try:
            if type(feed) is bytearray:
                feed = get_feed(feed)

            append_blob(feed, payload, self.keys[bytes(feed.fid)])
            return True
        except Exception:
            print("key not in dictionary")
            return False


# ------------------------------------------------------------------------------


def get_feed_overview() -> str:
    # not very optimized for pycom
    string_builder = []
    is_feed = lambda fn: fn.endswith(".head")
    fn2bytes = lambda fn: bytearray(unhexlify(fn[:-5].encode()))
    fids = list(map(fn2bytes, list(filter(is_feed, listdir("_feeds")))))

    for fid in fids:
        feed = get_feed(fid)
        if get_parent(feed):
            continue
        else:
            string_builder.append(to_string(feed))

        # add children below
        children = [(x, y, 0) for x, y in get_children(feed, index=True)]
        while children:
            child, index, offset = children.pop(0)
            assert type(child) is bytearray
            child_feed = get_feed(child)
            child_str = to_string(child_feed)

            # adjust padding
            padding_len = index - feed.anchor_seq + offset
            padding = "      " * padding_len
            child_str = "\n".join(
                ["".join([padding, s]) for s in child_str.split("\n")]
            )
            string_builder.append(child_str)

            # check for child of child
            child_children = get_children(child_feed, index=True)
            del child_feed
            child_children = [(x, y, padding_len) for x, y in child_children]
            del padding_len
            children = child_children + children

    return "\n".join(string_builder)
