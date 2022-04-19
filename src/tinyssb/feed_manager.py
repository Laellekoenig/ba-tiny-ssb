import os
import sys
from .feed import Feed
from .packet import create_child_pkt
from .packet import create_contn_pkt
from .packet import create_end_pkt
from .packet import create_parent_pkt
from .ssb_util import from_hex
from .ssb_util import is_file
from .ssb_util import to_hex

# non-micropython import
if sys.implementation.name != "micropython":
    # Optional type annotations are ignored in micropython
    from typing import Optional
    from typing import Union
    from typing import Dict


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
        self.feed_dir = self.path + "_feeds"
        self.blob_dir = self.path + "_blobs"
        self._check_dirs()
        self.feeds = self._get_feeds()

    def __len__(self):
        return len(self.feeds)

    def __getitem__(self, i: int) -> Feed:
        return self.feeds[i]

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

    def create_feed(self,
                    fid: Union[bytes, str],
                    skey: Union[bytes, str, None] = None,
                    trusted_seq: Union[int, bytes] = 0,
                    trusted_mid: Optional[bytes] = None,
                    parent_seq: Union[int, bytes] = 0,
                    parent_fid: bytes = bytes(32)) -> Optional[Feed]:
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
        assert (skey is None or
                type(skey) is bytes), "skey string to bytes conversion failed"

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
        return feed

    def create_child_feed(self,
                          parent_fid: Union[bytes, Feed],
                          child_fid: bytes,
                          child_skey: bytes) -> Optional[Feed]:
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
        if (parent is None or
            parent.skey is None or
            parent.front_mid is None):
            return None

        # add child info to parent
        parent_seq = (parent.front_seq + 1).to_bytes(4, "big")
        parent_pkt = create_parent_pkt(parent.fid, parent_seq,
                                       parent.front_mid, child_fid,
                                       parent.skey)

        assert parent_pkt.wire is not None, "failed to sign packet"

        # create child feed
        child_payload = parent_pkt.fid + parent_pkt.seq
        child_payload += parent_pkt.wire[-12:]
        child_feed = self.create_feed(child_fid,
                                      skey=child_skey,
                                      parent_fid=parent.fid,
                                      parent_seq=parent.front_seq)
        assert child_feed is not None, "failed to create child feed"

        child_pkt = create_child_pkt(child_feed.fid, child_payload, child_skey)

        # finally add packets
        child_feed.append_pkt(child_pkt)
        parent.append_pkt(parent_pkt)
        return child_feed

    def create_contn_feed(self,
                          end_fid: Union[bytes, Feed],
                          contn_fid: bytes,
                          contn_skey: bytes) -> Optional[Feed]:
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
        if (ending_feed is None
            or ending_feed.front_mid is None
            or ending_feed.skey is None):
            return None

        end_seq = (ending_feed.front_seq + 1).to_bytes(4, "big")
        end_pkt = create_end_pkt(ending_feed.fid, end_seq,
                                 ending_feed.front_mid, contn_fid,
                                 ending_feed.skey)

        assert end_pkt.wire is not None, "failed to sign ending packet"

        # create continuing feed
        contn_payload = end_pkt.fid + end_pkt.seq
        contn_payload += end_pkt.wire[-12:]
        contn_feed = self.create_feed(contn_fid,
                                      skey=contn_skey,
                                      parent_fid=ending_feed.fid,
                                      parent_seq=ending_feed.front_seq)
        assert contn_feed is not None, "failed to create continuation feed"

        contn_pkt = create_contn_pkt(contn_feed.fid, contn_payload, contn_skey)

        # finally add packets
        contn_feed.append_pkt(contn_pkt)
        ending_feed.append_pkt(end_pkt)
        return contn_feed
