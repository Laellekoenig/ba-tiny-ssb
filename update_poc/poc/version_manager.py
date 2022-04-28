import os
import json
from tinyssb.feed import Feed
from tinyssb.ssb_util import to_hex
from tinyssb.feed_manager import FeedManager

class VersionManager:

    path = None
    cfg_file_name = None
    feed_manager = None
    update_feed = None
    may_update = False
    vc_dict = {}

    @classmethod
    def init(cls, path: str, feed_manager = FeedManager) -> None:
        cls.path = path
        cls.cfg_file_name = cls.path + "/config.json"
        cls.feed_manager = feed_manager
        # load config
        cls._load_config()

    @classmethod
    def _load_config(cls) -> None:
        assert cls.path is not None, "call class first"
        file_name = cls.path + "/config.json"

        if file_name not in os.listdir(cls.path):
            # no config found -> empty dict
            cls.vc_dict = {}
        else:
            f = open(file_name, "r")
            json_str = f.read()
            f.close()
            # load and set dict
            cls.vc_dict = json.loads(json_str)

    @classmethod
    def _save_config(cls) -> None:
        assert cls.cfg_file_name is not None, "call class first"

        # save version control dict
        json_str = json.dumps(cls.vc_dict)
        f = open(cls.cfg_file_name, "w")
        f.write(json_str)
        f.close()

    @classmethod
    def set_update_feed(cls, update_feed: Feed) -> None:
        assert cls.feed_manager is not None, "call class first"
        print("setting update feed")
        cls.update_feed = update_feed

        # check if the key is available -> allowed to write new updates
        if to_hex(cls.update_feed.fid) not in cls.feed_manager.keys:
            # not allowed to append
            cls.may_update = False
            return

        cls.may_update = True
        # check files
        files = os.listdir(cls.path)
        for f in files:
            if f not in cls.vc_dict and f != cls.cfg_file_name:
                # create new update feed for file
                print(f)

        cls._save_config()
