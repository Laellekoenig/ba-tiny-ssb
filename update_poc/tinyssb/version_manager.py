from .feed_manager import FeedManager
from typing import List, Union, Tuple
import pure25519


def create_keypair() -> Tuple[bytes, bytes]:
    key, _ = pure25519.create_keypair()
    skey = key.sk_s[:32]
    vkey = key.vk_s
    return (skey, vkey)


class VersionManager:

    file_dict = None
    feed_manager = None
    update_feeds = None
    emergency_feeds = None

    @classmethod
    def set_feed_manager(cls, fm: FeedManager) -> None:
        cls.feed_manager = fm

    @classmethod
    def add_files(cls, file_names: Union[List[str], str]) -> None:
        """
        Takes a file name or a list of file name.
        Every file that is not registered yet, is added to the file_dict
        together with a newly created feed. The first entry of each new feed
        is a reference to a child 'emergency' feed.
        """
        assert cls.feed_manager is not None, "missing access to feed manager"
        if type(file_names) is str:
            file_names = [file_names]

        if cls.file_dict is None:
            cls.file_dict = {}

        if cls.emergency_feeds is None:
            cls.emergency_feeds = {}

        for file_name in file_names:
            if file_name in cls.file_dict:
                # already exists
                continue

            # create new feed
            skey, vkey = create_keypair()
            feed = cls.feed_manager.create_feed(vkey, skey=skey)
            assert feed is not None, "failed to create new feed"
            cls.file_dict[file_name, feed.fid]

            # create 'emergency road'
            e_skey, e_vkey = create_keypair()
            emergency_feed = cls.feed_manager.create_child_feed(feed,
                                                                e_vkey,
                                                                e_skey)
            assert emergency_feed is not None, "failed to create emergency feed"
            cls.emergency_feeds[file_name] = emergency_feed.fid
