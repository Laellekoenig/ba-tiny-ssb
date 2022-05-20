from .feed import (
    get_children,
    get_feed,
    get_next_dmx,
    get_parent,
    get_want,
    listdir,
    to_string,
    waiting_for_blob,
)
from _thread import allocate_lock
from json import dumps, loads
from os import mkdir
from pure25519 import create_keypair
from sys import implementation
from ubinascii import unhexlify


# helps debugging in vim
if implementation.name != "micropython":
    from typing import Dict, Tuple, List, Callable


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
        f.write(dumps(self.keys))
        f.close()

    def _load_config(self) -> None:
        file_name = "fm_config.json"
        if file_name not in listdir():
            return

        f = open(file_name)
        self.keys = loads(f.read())
        f.close()

    def update_keys(self, keys: Dict[str, str]) -> None:
        self.keys = keys
        self._save_config()

    def generate_keypair(self) -> Tuple[bytearray, bytearray]:
        key, _ = create_keypair()
        skey = bytearray(key.sk_s[:32])
        vkey = bytearray(key.vk_s)
        del key
        return skey, vkey

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
                    self.dmx_table[blob_ptr] = (self.handle_blob, fid)
                else:
                    self.dmx_table[get_next_dmx(feed)] = (self.handle_packet, fid)

    def consult_dmx(
        self, msg: bytearray
    ) -> Optional[Tuple[Callable[[bytearray, bytearray], None]], bytearray]:
        pass

    def handle_want(self) -> None:
        pass

    def handle_packet(self) -> None:
        pass

    def handle_blob(self) -> None:
        pass
