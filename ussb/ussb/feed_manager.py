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
    """
    Used for managing feeds and their corresponding feeds.
    Handles the dmx table and incoming packets/blobs.
    Allows registering of callback functions on feeds.
    These callback functions are called every time something is appended to the
    registered feed.
    """

    # minor boost for pycom device performance
    __slots__ = (
        "_callbacks",
        "callback_lock",
        "dmx_lock",
        "dmx_table",
        "fids",
        "keys",
    )

    def __init__(self) -> None:
        self._create_dirs()
        self.keys = {}
        self._load_config()
        self.fids = self.listfids()

        # dmx and callbacks
        self.dmx_lock = allocate_lock()
        self.dmx_table = {}
        self._fill_dmx()
        self.callback_lock = allocate_lock()
        self._callbacks = {}

    def _create_dirs(self) -> None:
        """
        Creates the needed feed and blob parent directories if they do not exist yet.
        """
        feeds = "_feeds"
        if feeds not in listdir():
            mkdir(feeds)

        blobs = "_blobs"
        if blobs not in listdir():
            mkdir(blobs)

    def _save_config(self) -> None:
        """
        Saves the currently stored dictionary of keys and feed IDs to a .json file.
        """
        f = open("fm_config.json", "w")
        f.write(
            dumps(
                {hexlify(k).decode(): hexlify(v).decode() for k, v in self.keys.items()}
            )
        )
        f.close()

    def _load_config(self) -> None:
        """
        Loads the dictionary containing keys and their corresponding feed IDs
        from the saved .json file.
        Does nothing if the file does not exist.
        """
        file_name = "fm_config.json"
        if file_name not in listdir():
            return

        f = open(file_name)
        str_dict = loads(f.read())
        f.close()

        self.keys = {
            unhexlify(k.encode()): unhexlify(v.encode()) for k, v in str_dict.items()
        }

    def update_keys(self, keys: Dict[bytes, bytes]) -> None:
        """
        Updates and saves the complete key dictionary.
        """
        self.keys = keys
        self._save_config()

    def generate_keypair(self, save_keys: bool = True) -> Tuple[bytearray, bytearray]:
        """
        Generates a new pure25519 key pair and returns them as a tuple:
        (signing key, verification key)
        Also saves the new key pair to the self.keys dictionary.
        This can be disabled by setting save_keys=False
        """
        key, _ = create_keypair()
        skey = key.sk_s[:32]
        vkey = key.vk_s

        if save_keys:
            self.keys[vkey] = skey
            self._save_config()
        return bytearray(skey), bytearray(vkey)

    def listfids(self) -> List[bytearray]:
        """
        Returns a list of all feed IDs that are saved locally.
        """
        is_feed = lambda fn: fn.endswith(".head")
        fn2bytes = lambda fn: bytearray(unhexlify(fn[:-5].encode()))
        return list(map(fn2bytes, list(filter(is_feed, listdir("_feeds")))))

    def __str__(self) -> str:
        """
        Returns a string representation of all locally saved feeds.
        This is used in the web GUI.
        Not optimized for pycom (very slow).
        """
        # FIXME: optimize for pycom
        string_builder = []
        for fid in self.fids:
            feed = get_feed(fid)
            if get_parent(feed):
                continue
            else:
                string_builder.append(to_string(feed))

            # add children below parent feed
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
        """
        Returns the number of locally stored feeds.
        """
        return len(self.fids)

    def __getitem__(self, i: int) -> bytearray:
        """
        Returns the feed ID of the given index.
        """
        return self.fids[i]

    def _fill_dmx(self) -> None:
        """
        Fills the dmx table of the file manager.
        Called on start-up.
        The dmx table is a dictionary containing:
        {dmx: (handling function, feed ID)}
        """
        with self.dmx_lock:
            for fid in self.listfids():
                feed = get_feed(fid)
                b_fid = bytes(feed.fid)

                # add want to dmx
                want = get_want(feed)[:7]
                self.dmx_table[bytes(want)] = (self.handle_want, b_fid)

                # if key is not present -> add dmx value of next blob/packet
                if bytes(fid) not in self.keys:
                    blob_ptr = waiting_for_blob(feed)
                    if blob_ptr:
                        self.dmx_table[bytes(blob_ptr)] = (self.handle_blob, b_fid)
                    else:
                        self.dmx_table[bytes(get_next_dmx(feed))] = (
                            self.handle_packet,
                            b_fid,
                        )

    def get_key(self, fid: bytearray) -> Optional[bytearray]:
        """
        Returns the key of the given feed ID.
        If no key is present, None is returned.
        """
        b_fid = bytes(fid)
        with self.dmx_lock:
            if b_fid not in self.keys:
                return None
            return self.keys[b_fid]

    def consult_dmx(
        self, msg: bytearray
    ) -> Optional[Tuple[Callable[[bytearray, bytearray], None], bytearray]]:
        """
        Checks the dmx table for the given dmx value.
        If the value is present, the handling function and feed ID are returned.
        """
        b_msg = bytes(msg)
        with self.dmx_lock:
            if b_msg not in self.dmx_table:
                return None
            return self.dmx_table[b_msg]

    def handle_want(self, fid: bytearray, request: bytearray) -> Optional[bytearray]:
        """
        Handling function for incoming want requests.
        Fetches the asked packet/blob, if available and returns it.
        """
        req_feed = get_feed(fid)
        req_seq = int.from_bytes(request[39:43], "big")

        # check seq number
        if req_feed.front_seq < req_seq:
            return None

        # get packet
        req_wire = bytearray(128)
        if len(request) == 43:
            # packet
            req_wire[:] = get_wire(req_feed, req_seq)
        else:
            # blob, len(request) == 63
            blob_ptr = request[-20:]
            try:
                hex_ptr = hexlify(blob_ptr).decode()
                f = open("_blobs/{}/{}".format(hex_ptr[:2], hex_ptr[2:]), "rb")
                req_wire[:] = f.read(128)
                f.close()
            except Exception:
                # blob not found
                return None

        return req_wire

    def handle_packet(self, fid: bytearray, wire: bytearray) -> None:
        """
        Handling function for incoming packets.
        The packet is verified and appended.
        Updates the dmx table and executes possible callback functions.
        """
        feed = get_feed(fid)
        wpkt = struct(addressof(wire), WIRE_PACKET, BIG_ENDIAN)
        if not verify_and_append_bytes(feed, wire):
            # verification failed, invalid packet
            return

        next_dmx = get_next_dmx(feed)

        blob_ptr = waiting_for_blob(feed)
        if next_dmx == wpkt.dmx and blob_ptr is None:
            # nothing was appended
            return None

        # update dmx value
        with self.dmx_lock:
            del self.dmx_table[bytes(wpkt.dmx)]
            if blob_ptr is None:
                self.dmx_table[bytes(next_dmx)] = self.handle_packet, bytes(fid)
            else:
                self.dmx_table[bytes(blob_ptr)] = self.handle_blob, bytes(fid)
                return

        # check for child or continuation feed
        front_wire = get_wire(feed, -1)
        if front_wire[15:16] in [
            CONTDAS.to_bytes(1, "big"),
            MKCHILD.to_bytes(1, "big"),
        ]:
            # create new feed and add to dmx table
            new_feed = create_feed(
                front_wire[16:48], parent_seq=feed.front_seq, parent_fid=fid
            )
            with self.dmx_lock:
                b_fid = bytes(new_feed.fid)
                want = get_want(new_feed)[:7]
                self.dmx_table[bytes(want)] = (self.handle_want, b_fid)
                next_dmx = get_next_dmx(new_feed)
                self.dmx_table[bytes(next_dmx)] = (self.handle_packet, b_fid)

        # execute callbacks, extract functions first to avoid blocked lock
        fn_lst = []
        self.callback_lock.acquire()
        if fid in self._callbacks:
            fn_lst.append(self._callbacks[fid])
        self.callback_lock.release()

        # execute
        for fns in fn_lst:
            [fn(fid) for fn in fns]

    def handle_blob(self, fid: bytearray, blob: bytearray) -> None:
        """
        Handling function for incoming blobs.
        The blob is verified and appended.
        Updates the dmx table and executes possible callback functions.
        """
        feed = get_feed(fid)

        if not verify_and_append_blob(feed, blob):
            # invalid blob
            return

        # update dmx table
        signature = sha256(blob[8:]).digest()[:20]
        with self.dmx_lock:
            del self.dmx_table[signature]

        next_ptr = waiting_for_blob(feed)
        if not next_ptr:
            # blob was last of chain, packet is next
            with self.dmx_lock:
                self.dmx_table[bytes(get_next_dmx(feed))] = self.handle_packet, bytes(
                    fid
                )

            # execute callbacks, avoid blocked lock
            fn_lst = []
            self.callback_lock.acquire()
            if fid in self._callbacks:
                fn_lst.append(self._callbacks[fid])
            self.callback_lock.release()

            # execute
            for fns in fn_lst:
                [fn(fid) for fn in fns]
            return

        # expecting another blob
        with self.dmx_lock:
            self.dmx_table[bytes(next_ptr)] = self.handle_blob, bytes(fid)

        # no callback functions, since the blob is not complete

    def register_callback(self, fid: bytearray, function) -> None:
        """
        Registers the given function to the given feed ID.
        This function is executed every time a new packet is appended or a
        blob chain has been completed.
        """
        b_fid = bytes(fid)

        with self.callback_lock:
            if b_fid not in self._callbacks:
                self._callbacks[b_fid] = [function]
            else:
                functions = self._callbacks[b_fid]
                if functions is None:
                    functions = [function]
                else:
                    functions.append(function)
                self._callbacks[b_fid] = functions

    def remove_callbacks(self, fid: bytearray) -> None:
        """
        Removes all callback functions of the given feed ID.
        """
        b_fid = bytes(fid)

        with self.callback_lock:
            if b_fid not in self._callbacks:
                return
            
            del self._callbacks[b_fid]

    def append_to_feed(
        self, feed: Union[bytearray, struct[FEED]], payload: bytearray
    ) -> bool:
        """
        Appends the given payload as a PLAIN48 packet to the given feed.
        If the key cannot be found, the packet is not appended and
        False is returned.
        """
        if type(feed) is bytearray:
            feed = get_feed(feed)
        try:
            append_bytes(feed, payload, self.keys[bytes(feed.fid)])
            return True
        except Exception:
            print("key not in dictionary")
            return False

    def append_blob_to_feed(
        self, feed: Union[bytearray, struct[FEED]], payload: bytearray
    ) -> bool:
        """
        Appends the given payload as a CHAIN20 packet/blob chain to the given feed.
        If the key cannot be found, the packet is not appended and
        False is returned.
        """
        if type(feed) is bytearray:
            feed = get_feed(feed)
        try:
            append_blob(feed, payload, self.keys[bytes(feed.fid)])
            return True
        except Exception:
            print("key not in dictionary")
            return False


def get_feed_overview() -> str:
    """
    Identical to FeedManager.__str__.
    Used for creating a string representation of all available feeds without
    creating or passing an instance of the FeedManager class.
    Not optimized for pycom devices, very slow.
    """
    string_builder = []
    is_feed = lambda fn: fn.endswith(".head")
    fn2bytes = lambda fn: bytearray(unhexlify(fn[:-5].encode()))
    fids = list(map(fn2bytes, list(filter(is_feed, listdir("_feeds")))))

    for fid in fids:
        feed = get_feed(fid)
        if get_parent(feed) is not None:
            continue
        else:
            string_builder.append(to_string(feed))

        # add children of feed below
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
