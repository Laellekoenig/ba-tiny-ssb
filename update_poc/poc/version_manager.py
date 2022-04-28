import os
import json
from tinyssb.feed import Feed
from tinyssb.ssb_util import to_hex, create_keypair, from_hex
from tinyssb.feed_manager import FeedManager

class VersionManager:

    def __init__(self, path: str, feed_manager: FeedManager) -> None:
        self.path = path
        self.cfg_file_name = path + "/config.json"
        self.feed_manager = feed_manager
        self.vc_dict = {}
        self._load_config()
        # TODO
        self.update_feed = None
        self.may_update = False

    def __del__(self) -> None:
        self._save_config()

    def is_configured(self) -> bool:
        return self.update_feed is not None

    def _load_config(self) -> None:
        if self.cfg_file_name not in os.listdir(self.path):
            # no config found -> empty dict
            self.vc_dict = {}
        else:
            # file exists
            f = open(self.cfg_file_name, "r")
            json_str = f.read()
            f.close()
            # load and set dict
            str_dict = json.loads(json_str)
            self.vc_dict = {k: (from_hex(v[0]), from_hex(v[1]))
                            for k, v in str_dict.items()}

    def _save_config(self) -> None:
        # save version control dict
        str_dict = {k: (to_hex(v[0]), to_hex(v[1]))
                    for k, v in self.vc_dict.items()}
        json_str = json.dumps(str_dict)
        f = open(self.cfg_file_name, "w")
        f.write(json_str)
        f.close()

    def set_update_feed(self, update_feed: Feed) -> None:
        self.update_feed = update_feed

        # check if the key is available -> allowed to write new updates
        if to_hex(self.update_feed.fid) not in self.feed_manager.keys:
            # not allowed to append
            self.may_update = False
            return

        self.may_update = True
        # check files
        files = os.listdir(self.path)
        for f in files:
            if (f not in self.vc_dict and
                f != self.cfg_file_name.split("/")[-1]):
                # create new update feed for file
                skey, vkey = create_keypair()
                new = self.feed_manager.create_child_feed(self.update_feed,
                                                          vkey, skey)
                assert new is not None, "failed to create new file feed"
                new.append_blob(f.encode())
                skey, vkey = create_keypair()
                # create emergency feed
                emergency = self.feed_manager.create_child_feed(new,
                                                                vkey, skey)
                assert emergency is not None, "failed to create emergency feed"
                emergency.append_blob(f"{f} - emergency".encode())
                self.vc_dict[f] = (new.fid, emergency.fid)

        self._save_config()
