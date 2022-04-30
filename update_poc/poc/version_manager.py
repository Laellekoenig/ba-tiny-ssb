import os
import sys
import json
from tinyssb.feed import Feed
from tinyssb.ssb_util import to_hex, create_keypair, from_hex
from tinyssb.feed_manager import FeedManager
from tinyssb.packet import PacketType
from .version_util import apply_changes, delta_from_bytes, get_file_delta


# non-micropython import
if sys.implementation.name != "micropython":
    # Optional type annotations are ignored in micropython
    pass


class VersionManager:

    def __init__(self, path: str, feed_manager: FeedManager) -> None:
        self.path = path
        self.cfg_file_name = path + "/config.json"
        self.feed_manager = feed_manager
        self.vc_dict = {}
        self._load_config()
        # TODO
        self.update_feed = None
        self.vc_feed = None
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

    def update_feed_changed(self, fid: bytes) -> None:
        assert self.update_feed is not None, "set update feed first"
        assert self.update_feed.fid == fid, "not update feed"

        if self.update_feed.waiting_for_blob() is not None:
            # waiting for blob
            return

        if self.vc_feed is None:
            # check if vc feed was added
            children = self.update_feed.get_children()
            if len(children) >= 1:
                self.vc_feed = self.feed_manager.get_feed(children[0])
                # register callback
                self.feed_manager.register_callback(self.vc_feed.fid,
                                                    self.vc_feed_changed)
                return
            else:
                return  # waiting for vc feed

        # new update file
        new_fid = self.update_feed.get_children()[-1]
        self.feed_manager.register_callback(new_fid, self.feed_changed)

    def vc_feed_changed(self, _: bytes) -> None:
        assert self.vc_feed is not None, "vc feed not found"
        front_type = self.vc_feed.get_type(-1)
        if front_type == PacketType.ischild:
            # first packet in feed
            return
        print("vc change")

    def feed_changed(self, fid: bytes) -> None:
        # TODO: create file if not exists
        feed = self.feed_manager.get_feed(fid)
        if feed.waiting_for_blob() is not None:
            # blob not complete
            return

        # handle differently, depending on new pkt
        front_type = feed.get_type(-1)
        if front_type == PacketType.chain20:
            print("update arrived")
            self._apply_update(feed.get_upd_file_name(), feed[-1])
            return
        if front_type == PacketType.mkchild:
            # setup of update feed finished
            file_name = feed.get_upd_file_name()
            emergency_fid = feed.get_children()[0]
            self.vc_dict[file_name] = (feed.fid, emergency_fid)
            self._save_config()
            print("creating emergency feed")

    def _apply_update(self, file_name: str, changes: bytes) -> None:
        delta = delta_from_bytes(changes)
        # TODO: not instantly apply changes
        apply_changes(self.path, file_name, delta)

    def set_update_feed(self, update_feed: Feed) -> None:
        self.update_feed = update_feed

        # check if vc feed is already available
        children = update_feed.get_children()
        if len(children) >= 1:
            self.vc_feed = children[0]

        # check if the key is available -> allowed to write new updates
        if to_hex(self.update_feed.fid) not in self.feed_manager.keys:
            # not allowed to append
            self.may_update = False
            # register callback function, in case new update arrives
            self.feed_manager.register_callback(update_feed.fid,
                                                self.update_feed_changed)
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
                new.add_upd_file_name(f)  # add file name to feed (2nd pos)
                skey, vkey = create_keypair()
                # create emergency feed
                emergency = self.feed_manager.create_child_feed(new,
                                                                vkey, skey)
                assert emergency is not None, "failed to create emergency feed"
                emergency.add_upd_file_name(f)  # add file name to feed
                self.vc_dict[f] = (new.fid, emergency.fid)
                self._save_config()

        self._save_config()

    def update_file(self, file_name: str, content: str) -> None:
        if not self.may_update:
            print("may not append new updates")
            return

        if file_name not in self.vc_dict:
            print("file does not exist")
            # TODO: create new file
            return

        # get difference between old file and new file
        delta = get_file_delta(self.path, file_name, content)

        # append to feed
        fid, _ = self.vc_dict[file_name]
        feed = self.feed_manager.get_feed(fid)
        assert feed is not None, "failed to get feed"

        feed.append_blob(delta)
