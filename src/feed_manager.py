import os
from feed import Feed
from packet import create_child_pkt
from packet import create_contn_pkt
from packet import create_end_pkt
from packet import create_parent_pkt
from ssb_util import from_hex
from ssb_util import is_file
from ssb_util import to_hex
from pure25519 import create_keypair
from typing import Optional


class FeedManager:
    """
    Manages and creates Feed instances.
    The path can be specified in the constructor with path="path".
    Also takes an optional dictionary, containing feed IDs (as strings)
    as keys with their signing keys (as strings) as values.
    """

    def __init__(self, path: str = "", keys: dict[str, str] = None):
        self.path = path
        self.keys = keys
        self.feed_dir = self.path + "_logs"
        self.blob_dir = self.path + "_blobs"
        self._check_dirs()
        self.feeds = self._get_feeds()

    def __len__(self):
        return len(self.feeds)

    def __getitem__(self, i: int) -> Feed:
        return self.feeds[i]

    def _check_dirs(self):
        """
        Checks whether the _log and _blob directories already exist.
        If not, new directories are created.
        """
        if not is_file(self.feed_dir):
            os.mkdir(self.feed_dir)
        if not is_file(self.blob_dir):
            os.mkdir(self.blob_dir)

    def _get_feeds(self) -> list[Feed]:
        """
        Reads all .log files in the self.feed_dir directory.
        Returns a list of all Feed instances.
        """
        feeds = []
        files = os.listdir(self.feed_dir)
        for f in files:
            if f.endswith(".log"):
                skey = self._get_skey(f)
                feeds.append(Feed(self.feed_dir + "/" + f, skey=skey))

        return feeds

    def _get_skey(self, fn: str) -> bytes:
        """
        Checks whether the given file name has an associated signing key
        in the self.keys dictionary.
        """
        fid = fn.split(".")[0]
        try:
            assert self.keys is not None
            return from_hex(self.keys[fid])
        except Exception:
            return None

    def get_feed(self, fid: bytes) -> Feed:
        """
        Searches for a specific Feed in self.feeds.
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
                    fid: bytes = None,
                    trusted_seq: int = 0,
                    trusted_mid: bytes = None,
                    parent_seq: int = 0,
                    parent_fid: bytes = bytes(32)) -> Feed:
        """
        Creates a new Feed instance and adds it to self.feeds.
        The feed ID, trusted sequence number, trusted message ID,
        parent feed ID and parent sequence number can be explicitly
        specified.
        If no feed ID is specified, a random one is generated.
        The randomly generated feed_id is also the verification key.
        The secret signing key is added to the self.keys dict.
        Returns the newly created Feed instance.
        """
        if fid is None:
            keys, _= create_keypair()
            skey = keys.sk_s[:32]
            fid = keys.vk_s

            if self.keys is None:
                self.keys = {}
            self.keys[to_hex(fid)] = to_hex(skey)
        else:
            skey = None

        if trusted_mid is None:
            trusted_mid = fid[:20]  # tinyssb convention, self-signed

        if type(trusted_seq) is int:
            trusted_seq = trusted_seq.to_bytes(4, "big")
        if type(parent_seq) is int:
            parent_seq = parent_seq.to_bytes(4, "big")
        if trusted_mid is None:
            trusted_mid = bytes(20)

        assert type(trusted_seq) is bytes
        assert type(parent_seq) is bytes

        assert len(fid) == 32, "fid must be 32b"
        assert len(trusted_seq) == 4, "trusted seq must be 4b"
        assert len(trusted_mid) == 20, "trusted mid must be 20b"
        assert len(parent_seq) == 4, "parent seq must be 4b"
        assert len(parent_fid) == 32, "parent_fid must be 32b"

        # create log file
        file_name = self.feed_dir + "/" + to_hex(fid) + ".log"
        if is_file(file_name):
            return None

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
        return feed

    def create_child_feed(self, parent_fid: bytes,
                          child_fid: bytes = None) -> Feed:
        """
        Creates and returns a new child Feed instance for the given parent.
        The parent can be passed either as a Feed instance, feed ID bytes,
        feed ID hex string or file name.
        The child feed ID can be explicitly definied.
        """
        if type(parent_fid) is Feed:
            parent = parent_fid
        else:
            parent = self.get_feed(parent_fid)

        if parent is None:
            return None

        assert parent.skey is not None, "must have signing key of parent"
        assert parent.front_mid is not None

        if child_fid is None:
            child_fid = os.urandom(32)

        # add child info to parent
        parent_seq = (parent.front_seq + 1).to_bytes(4, "big")
        parent_pkt = create_parent_pkt(parent.fid, parent_seq,
                                       parent.front_mid, child_fid,
                                       parent.skey)

        assert parent_pkt.wire is not None, "failed to sign packet"
        parent.append_pkt(parent_pkt)

        # create child feed
        child_payload = parent_pkt.fid + parent_pkt.seq
        child_payload += parent_pkt.wire[-12:]
        child_feed = self.create_feed(child_fid,
                                      parent_fid=parent.fid,
                                      parent_seq=parent.front_seq)

        assert child_feed is not None, "failed to create child feed"
        child_pkt = create_child_pkt(child_feed.fid, child_payload,
                                     parent.skey)  # for now, key of parent
        child_feed.append_pkt(child_pkt)
        return child_feed

    def create_contn_feed(self, end_fid: bytes,
                          contn_fid: bytes = None) -> Feed:
        """
        Ends the given feed and returns a new continuation Feed instance.
        The ending feed can be passed either as a Feed instance, feed ID bytes,
        feed ID hex string or file name.
        The continuation feed ID can be explicitly defined.
        """
        if type(end_fid) is Feed:
            ending_feed = end_fid
        else:
            ending_feed = self.get_feed(end_fid)

        if (ending_feed is None or ending_feed.front_mid is None
                or ending_feed.skey is None):
            return None

        if contn_fid is None:
            contn_fid = os.urandom(32)

        end_seq = (ending_feed.front_seq + 1).to_bytes(4, "big")
        end_pkt = create_end_pkt(ending_feed.fid, end_seq,
                                 ending_feed.front_mid, contn_fid,
                                 ending_feed.skey)

        assert end_pkt.wire is not None, "failed to sign ending packet"

        ending_feed.append_pkt(end_pkt)
        # create continuing feed
        contn_payload = end_pkt.fid + end_pkt.seq
        contn_payload += end_pkt.wire[-12:]
        contn_feed = self.create_feed(contn_fid,
                                          parent_fid=ending_feed.fid,
                                          parent_seq=ending_feed.front_seq)
        assert contn_feed is not None, "failed to create continuation feed"

        contn_pkt = create_contn_pkt(contn_feed.fid, contn_payload,
                                     ending_feed.skey)
        contn_feed.append_pkt(contn_pkt)
        return contn_feed
