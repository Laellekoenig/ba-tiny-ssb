import os
from tinyssb.feed_manager import FeedManager
from tinyssb.feed import Feed
from tinyssb.ssb_util import to_hex

class VersionManager:

    def __init__(self, path: str, feed_manager: FeedManager,
                 update_feed: Feed):
        self.path = path
        self.feed_manager = feed_manager
        self.update_feed = update_feed
        # is this the owner of the feed?
        self.may_update = to_hex(update_feed.fid) in self.feed_manager.keys

        if self.may_update:
            # check if all files have a subfeed
            files = os.listdir(self.path)
            for f in files:
                if not f.endswith(".py"):
                    files.remove(f)
