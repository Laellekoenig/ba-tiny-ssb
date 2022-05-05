import _thread
import os
import sys
from .feed import Feed
from .packet import (
    PacketType,
    create_child_pkt,
    create_contn_pkt,
    create_end_pkt,
    create_parent_pkt,
)
from .ssb_util import from_hex, is_file, to_hex
from hashlib import sha256

# non-micropython import
if sys.implementation.name != "micropython":
    # Optional type annotations are ignored in micropython
    from typing import Optional, Union, Dict, Callable, Tuple


class FeedManager:
    """
    Manages and creates Feed instances.
    The path can be specified in the constructor with path="path".
    Also takes a dictionary with feed IDs as keys, leading to their
    corresponding signing keys.
    If no dictionary is provided, an empty one is created.
    """

    def __init__(self, path: str = "", keys: Dict[str, str] = {}):
        self.path = path
        self.keys = keys
        self.feed_dir = self.path + "/" + "_feeds"
        self.blob_dir = self.path + "/" + "_blobs"
        self._check_dirs()
        self.feeds = self._get_feeds()

        # dmx table
        self.dmx_lock = _thread.allocate_lock()
        self.dmx_table = {}
        self._fill_dmx()

        # callback functions
        self._callback = {}

    def __str__(self) -> str:
        """
        Used for visualizing all currently available feeds.
        """
        string_builder = []
        for feed in self.feeds:
            if feed.get_parent() is not None:
                continue
            string_builder.append(str(feed))

            children = [(x, y, 0) for x, y in feed.get_children_index()]
            while children != []:
                child_tuple = children.pop(0)
                child, index, offset = child_tuple
                c_feed = self.get_feed(child)
                assert c_feed is not None, "failed to get feed"
                c_string = str(c_feed)

                # now adjust left padding
                padding_len = index - feed.anchor_seq + offset
                padding = " " * 6 * padding_len
                # add to c_string
                c_string = "\n".join([padding + s for s in c_string.split("\n")])
                string_builder.append(c_string)

                # check for child in child
                child_children = c_feed.get_children_index()
                # add parent padding
                child_children = [(x, y, padding_len) for (x, y) in child_children]
                children = child_children + children

            # create separator
            max_len = -1
            for string in string_builder:
                for substring in string.split("\n"):
                    if len(substring) > max_len:
                        max_len = len(substring)

            separator = "¨" * max_len
            string_builder.insert(0, separator)
            string_builder.append("")

        return "\n".join(string_builder)

    def __len__(self):
        return len(self.feeds)

    def __getitem__(self, i: int) -> Feed:
        return self.feeds[i]

    def register_callback(self, fid: Union[bytes, Feed], function) -> None:
        """
        Registers the given function as a callback function for the given feed.
        After a new packet or blob is appended (via handle_packet, or
        handle_blob) this function is executed.
        """
        if type(fid) is Feed:
            fid = fid.fid
        assert type(fid) is bytes, "failed to get FID from feed"

        if fid not in self._callback:
            self._callback[fid] = [function]
        else:
            lst = self._callback[fid]
            self._callback[fid] = lst + [function]

    def remove_callback(self, fid: Union[bytes, Feed], function) -> None:
        """
        Removes a given function from the registered callback functions of
        the given feed.
        """
        if type(fid) is Feed:
            fid = fid.fid
        assert type(fid) is bytes, "failed to get FID from feed"
        
        if fid not in self._callback:
            return

        functions = self._callback[fid]
        if function not in functions:
            return

        # remove
        functions.remove(function)
        self._callback[fid] = functions

    def update_keys(self, keys: Dict[str, str]) -> None:
        """
        Replaces the current keys dictionary with the given one.
        Also updates the keys in every feed instance -> allows appending.
        """
        self.keys = keys

        # transform hex string key to bytes format
        bytes_keys = {from_hex(k): from_hex(v) for k, v in keys.items()}

        # update individual feeds -> allow appending
        for fid in bytes_keys:
            feed = self.get_feed(fid)
            if feed is None:
                continue
            feed.skey = bytes_keys[fid]

    def _fill_dmx(self) -> None:
        """
        Fills the DMX table with all relevant DMX values and corresponding
        handlers.
        """
        self.dmx_lock.acquire()

        for feed in self:
            # check if next expected pkt is blob
            want = feed.get_want()[:7]  # for incoming want requests
            self.dmx_table[want] = (self.handle_want, feed.fid)

            blob_ptr = feed.waiting_for_blob()
            if blob_ptr is None:
                next_dmx = feed.get_next_dmx()
                self.dmx_table[next_dmx] = (self.handle_packet, feed.fid)
            else:
                self.dmx_table[blob_ptr] = (self.handle_blob, feed.fid)

        self.dmx_lock.release()

    def consult_dmx(
        self, msg: bytes
    ) -> Optional[Tuple[Callable[[bytes, bytes], None], bytes]]:
        """
        Returns the corresponding handling function and FID for a given
        DMX value. If no entry is found, None is returned.
        The handling function can be called as follows:
        fn, fid = consult_dmx(dmx)
        fn(fid)
        """
        self.dmx_lock.acquire()
        if msg not in self.dmx_table:
            # no entry found
            self.dmx_lock.release()
            return None

        fn, fid = self.dmx_table[msg]
        self.dmx_lock.release()
        return (fn, fid)

    def _check_dirs(self):
        """
        Checks whether the _feeds and _blobs directories already exist.
        If not, new directories are created.
        """
        # TODO: recursive creation of directories in subdirectories
        if not is_file(self.feed_dir):
            os.mkdir(self.feed_dir)
        if not is_file(self.blob_dir):
            os.mkdir(self.blob_dir)

    def _get_feeds(self) -> list[Feed]:
        """
        Reads all .log files in the self.feed_dir directory.
        Returns a list containing all corresponding Feed instances.
        """
        feeds = []
        files = os.listdir(self.feed_dir)
        for f in files:
            if f.endswith(".log"):
                skey = self._get_skey(f)
                feeds.append(Feed(self.feed_dir + "/" + f, skey=skey))

        return feeds

    def _get_skey(self, fn: str) -> Optional[bytes]:
        """
        Checks whether the given file name has an associated signing key
        in the self.keys dictionary.
        """
        fid = fn.split(".")[0]
        try:
            return from_hex(self.keys[fid])
        except Exception:
            return None

    def get_feed(self, fid: Union[bytes, str]) -> Optional[Feed]:
        """
        Searches for a specific Feed instance in self.feeds.
        The feed ID can be handed in as bytes, a hex string
        or a file name.
        Returns 'None' if the feed cannot be found.
        """
        # transform to bytes
        if type(fid) is str:
            if fid.endswith(".log"):
                fid = fid[:-4]
            fid = from_hex(fid)

        # search
        for feed in self.feeds:
            if feed.fid == fid:
                return feed

        return None

    def create_feed(
        self,
        fid: Union[bytes, str],
        skey: Union[bytes, str, None] = None,
        trusted_seq: Union[int, bytes] = 0,
        trusted_mid: Optional[bytes] = None,
        parent_seq: Union[int, bytes] = 0,
        parent_fid: bytes = bytes(32),
    ) -> Optional[Feed]:
        """
        Creates a new Feed instance and adds it to self.feeds.
        The signing key, trusted sequence number, trusted message ID,
        parent sequence number and parent feed ID can be explicitly defined.
        If no signing key is provided, it is not possible to sign new packets.
        -> only received (already signed) packets can be appended.
        Returns the newly created Feed instance.
        """
        # convert fid and skey to bytes, if necessary
        if type(fid) is str:
            fid = from_hex(fid)
        assert type(fid) is bytes, "fid string to bytes conversion failed"

        if type(skey) is str:
            skey = from_hex(skey)
        assert (
            skey is None or type(skey) is bytes
        ), "skey string to bytes conversion failed"

        if trusted_mid is None:
            trusted_mid = fid[:20]  # tinyssb convention, self-signed

        # int to bytes conversion (if needed)
        if type(trusted_seq) is int:
            trusted_seq = trusted_seq.to_bytes(4, "big")
        if type(parent_seq) is int:
            parent_seq = parent_seq.to_bytes(4, "big")
        if trusted_mid is None:
            trusted_mid = bytes(20)

        assert type(trusted_seq) is bytes, "int conversion failed"
        assert type(parent_seq) is bytes, "int conversion failed"

        # check lengths
        assert len(fid) == 32, "fid must be 32b"
        assert len(trusted_seq) == 4, "trusted seq must be 4b"
        assert len(trusted_mid) == 20, "trusted mid must be 20b"
        assert len(parent_seq) == 4, "parent seq must be 4b"
        assert len(parent_fid) == 32, "parent_fid must be 32b"

        # create log file
        file_name = self.feed_dir + "/" + to_hex(fid) + ".log"
        if is_file(file_name):
            return None

        # build header of feed
        header = bytes(12) + fid + parent_fid + parent_seq
        header += trusted_seq + trusted_mid
        header += trusted_seq + fid[:20]  # self-signed
        assert len(header) == 128, "header must be 128b"

        # create new log file
        f = open(file_name, "wb")
        f.write(header)
        f.close()

        feed = Feed(file_name, skey=skey)
        self.feeds.append(feed)
        if type(skey) is bytes:
            # add skey to dict if given
            self.keys[to_hex(fid)] = to_hex(skey)

        # add to dmx table
        want = feed.get_want()[:7]
        next_dmx = feed.get_next_dmx()
        self.dmx_lock.acquire()
        self.dmx_table[want] = (self.handle_want, feed.fid)
        self.dmx_table[next_dmx] = (self.handle_packet, feed.fid)
        self.dmx_lock.release()

        # add to dmx
        return feed

    def create_child_feed(
        self, parent_fid: Union[bytes, Feed], child_fid: bytes, child_skey: bytes
    ) -> Optional[Feed]:
        """
        Creates and returns a new child Feed instance for the given parent.
        The parent can be passed either as a Feed instance, feed ID bytes,
        feed ID hex string or file name.
        The child feed ID must be explicitly defined.
        The signing key must be provided.
        """
        parent = None
        # feed conversion
        if type(parent_fid) is Feed:
            parent = parent_fid
        if type(parent_fid) is bytes:
            parent = self.get_feed(parent_fid)

        # check properties of parent
        if parent is None or parent.skey is None or parent.front_mid is None:
            return None

        # add child info to parent
        parent_seq = (parent.front_seq + 1).to_bytes(4, "big")
        parent_pkt = create_parent_pkt(
            parent.fid, parent_seq, parent.front_mid, child_fid, parent.skey
        )

        assert parent_pkt.wire is not None, "failed to sign packet"

        # create child feed
        child_payload = parent_pkt.fid + parent_pkt.seq
        child_payload += parent_pkt.wire[-12:]
        child_feed = self.create_feed(
            child_fid,
            skey=child_skey,
            parent_fid=parent.fid,
            parent_seq=parent.front_seq,
        )
        assert child_feed is not None, "failed to create child feed"

        child_pkt = create_child_pkt(child_feed.fid, child_payload, child_skey)

        # finally add packets
        child_feed.append_pkt(child_pkt)
        parent.append_pkt(parent_pkt)
        return child_feed

    def create_contn_feed(
        self, end_fid: Union[bytes, Feed], contn_fid: bytes, contn_skey: bytes
    ) -> Optional[Feed]:
        """
        Ends the given feed and returns a new continuation Feed instance.
        The ending feed can be passed either as a Feed instance, feed ID bytes,
        feed ID hex string or file name.
        The continuation feed ID must be explicitly defined and
        the signing key must be provided.
        """
        ending_feed = None
        # feed conversion
        if type(end_fid) is Feed:
            ending_feed = end_fid
        if type(end_fid) is bytes:
            ending_feed = self.get_feed(end_fid)

        # check properties of ending feed
        if (
            ending_feed is None
            or ending_feed.front_mid is None
            or ending_feed.skey is None
        ):
            return None

        end_seq = (ending_feed.front_seq + 1).to_bytes(4, "big")
        end_pkt = create_end_pkt(
            ending_feed.fid, end_seq, ending_feed.front_mid, contn_fid, ending_feed.skey
        )

        assert end_pkt.wire is not None, "failed to sign ending packet"

        # create continuing feed
        contn_payload = end_pkt.fid + end_pkt.seq
        contn_payload += end_pkt.wire[-12:]
        contn_feed = self.create_feed(
            contn_fid,
            skey=contn_skey,
            parent_fid=ending_feed.fid,
            parent_seq=ending_feed.front_seq,
        )
        assert contn_feed is not None, "failed to create continuation feed"

        contn_pkt = create_contn_pkt(contn_feed.fid, contn_payload, contn_skey)

        # finally add packets
        contn_feed.append_pkt(contn_pkt)
        ending_feed.append_pkt(end_pkt)
        return contn_feed

    def handle_want(self, fid: bytes, request: bytes) -> Optional[bytes]:
        """
        Handles an incoming "want" request.
        Searches for the correct packet/blob.
        If the packet/blob cannot be found, None is returned.
        """
        requested_feed = self.get_feed(fid)
        assert requested_feed is not None, "failed to get feed"

        seq = int.from_bytes(request[39:43], "big")
        if requested_feed.front_seq < seq:
            # packet does not exist yet
            return None

        requested_wire = None
        if len(request) == 43:
            # regular feed entry request
            requested_wire = requested_feed.get_wire(seq)
            if requested_wire is None:
                print("pkt does not exist yet")
                return

        if len(request) == 63:
            # blob request
            blob_ptr = request[-20:]
            requested_blob = requested_feed._get_blob(blob_ptr)
            if requested_blob is None:
                print("did not find blob")
                # blob not found
                return
            requested_wire = requested_blob.wire

        return requested_wire

    def handle_packet(self, fid: bytes, wire: bytes) -> None:
        """
        Handles an incoming new packet.
        It is appended to the correct feed (if is can be verified).
        After appending, the DMX table is updated.
        Also creates new feeds, if the newly appended packet asks for it.
        At the end of the function all the registered callback functions are
        executed.
        """
        feed = self.get_feed(fid)
        assert feed is not None, "failed to get feed"

        # try to append
        if not feed.verify_and_append_bytes(wire):
            # packet is not trusted
            return

        next_dmx = feed.get_next_dmx()
        blob_ptr = feed.waiting_for_blob()

        if next_dmx == wire[:7] and blob_ptr is None:
            # nothing new was appended
            return

        # remove old DMX value and insert new value
        self.dmx_lock.acquire()

        self.dmx_table.pop(wire[:7], None)
        if blob_ptr is None:
            # expecting packet
            self.dmx_table[next_dmx] = (self.handle_packet, feed.fid)

            # debugging
            front_type = feed.get_type(-1)
            if front_type is PacketType.plain48 or front_type is PacketType.chain20:
                # print(feed[-1])
                pass
            if front_type is PacketType.updfile:
                # print("new update feed: {}".format(feed.get_upd_file_name()))
                pass
        else:
            # expecting blob
            self.dmx_table[blob_ptr] = (self.handle_blob, feed.fid)
            self.dmx_lock.release()
            return

        self.dmx_lock.release()

        # check if new continuation or child feed should be created
        front_type = feed.get_type(-1)
        new_fid = wire[8:40]

        if front_type == PacketType.mkchild or front_type == PacketType.contdas:
            _ = self.create_feed(
                new_fid, parent_fid=feed.fid, parent_seq=feed.front_seq
            )

        # execute callbacks
        if fid in self._callback:
            functions = self._callback[fid]
            for function in functions:
                function(fid)

    def handle_blob(self, fid: bytes, blob: bytes) -> None:
        """
        Verifies and appends a received blob to the given feed.
        After insertion, the DMX table is updated.
        At the end of the function, all of the registered callback functions
        are executed.
        """
        feed = self.get_feed(fid)
        assert feed is not None, "failed to get feed"

        # insert
        if not feed.verify_and_append_blob(blob):
            print("blob could not be verified")
            return

        signature = sha256(blob).digest()[:20]

        # update table: remove old pointer
        self.dmx_lock.acquire()
        self.dmx_table.pop(signature, None)
        self.dmx_lock.release()

        # check if blob has ended
        next_ptr = feed.waiting_for_blob()
        if next_ptr is None:
            # print(feed[-1])
            self.dmx_lock.acquire()
            # add dmx for next packet
            self.dmx_table[feed.get_next_dmx()] = (self.handle_packet, fid)
            self.dmx_lock.release()

            # execute callbacks
            if fid in self._callback:
                functions = self._callback[fid]
                for function in functions:
                    function(fid)
            return

        # add next pointer to table
        self.dmx_lock.acquire()
        self.dmx_table[next_ptr] = (self.handle_blob, feed.fid)
        self.dmx_lock.release()
