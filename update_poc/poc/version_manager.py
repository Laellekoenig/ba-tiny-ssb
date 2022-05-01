import json
import os
import sys
from .version_util import (
    apply_changes,
    bytes_to_changes,
    read_file,
    write_file,
    get_file_changes,
)
from tinyssb.feed import Feed
from tinyssb.feed_manager import FeedManager
from tinyssb.packet import PacketType
from tinyssb.ssb_util import to_hex, create_keypair, from_hex

# non-micropython import
if sys.implementation.name != "micropython":
    # Optional type annotations are ignored in micropython
    pass


class VersionManager:
    """
    Manages the update feed including applying and or adding new updates to
    or from the feed.
    """

    cfg_file_name = "update_cfg.json"

    def __init__(self, path: str, feed_manager: FeedManager) -> None:
        self.path = path
        self.feed_manager = feed_manager

        self.vc_dict = {}  # version control dictionary
        self._load_config()

        self.update_feed = None
        self.vc_feed = None
        self.may_update = False

    def __del__(self) -> None:
        self._save_config()

    def _load_config(self) -> None:
        """
        Loads the configuration file containing the version control dict.
        The file name of a monitored file is the key and a tuple consisting
        of the corresponding file update FID and emergency FID is is the
        associated value.
        """
        if self.path + "/" + self.cfg_file_name not in os.listdir(self.path):
            # no config found -> empty dict
            self.vc_dict = {}
        else:
            # file exists
            json_str = read_file(self.path, self.cfg_file_name)
            assert json_str is not None
            str_dict = json.loads(json_str)
            self.vc_dict = {
                k: (from_hex(v[0]), from_hex(v[1])) for k, v in str_dict.items()
            }

    def _save_config(self) -> None:
        """
        Saves the version control dictionary to a json file.
        """
        str_dict = {k: (to_hex(v[0]), to_hex(v[1])) for k, v in self.vc_dict.items()}
        json_str = json.dumps(str_dict)
        write_file(self.path, self.cfg_file_name, json_str)

    def is_configured(self) -> bool:
        return self.update_feed is not None

    def set_update_feed(self, update_feed: Feed) -> None:
        """
        Used for setting the update feed.
        Depending on if the key is available for the update feed,
        new updates may be appended by the update manager.
        """
        self.update_feed = update_feed

        # check if version control feed is already available
        children = update_feed.get_children()
        if len(children) >= 1:
            self.vc_feed = children[0]

        # check if the key is available -> allowed to write new updates
        if to_hex(self.update_feed.fid) not in self.feed_manager.keys:
            self.may_update = False
            # register callback function, in case that new update arrives
            self.feed_manager.register_callback(
                update_feed.fid, self._update_feed_callback
            )
            return

        self.may_update = True
        # callback not needed -> manager of update feed

        # check monitored files
        files = os.listdir(self.path)
        for f in files:
            if f not in self.vc_dict and f != self.cfg_file_name:
                # create new update feed for file
                skey, vkey = create_keypair()
                new = self.feed_manager.create_child_feed(self.update_feed, vkey, skey)
                assert new is not None, "failed to create new file feed"
                new.add_upd_file_name(f) # add file name to feed

                # create emergency feed
                skey, vkey = create_keypair()
                emergency = self.feed_manager.create_child_feed(new, vkey, skey)
                assert emergency is not None, "failed to create emergency feed"
                emergency.add_upd_file_name(f)  # add file name to feed

                # save to version control dictionary
                self.vc_dict[f] = (new.fid, emergency.fid)

        self._save_config()

    def _update_feed_callback(self, fid: bytes) -> None:
        """
        Callback function that is registered to the main update feed.
        Updates the version control dict according to new entries.
        Also creates new file update feeds.
        """
        assert self.update_feed is not None, "no update feed set"
        assert self.update_feed.fid == fid, "not called on update feed"

        if self.update_feed.waiting_for_blob() is not None:
            # waiting for blob
            return

        if self.vc_feed is None:
            # check if version control feed was added (first child)
            children = self.update_feed.get_children()
            if len(children) >= 1:
                self.vc_feed = self.feed_manager.get_feed(children[0])
                # register callback
                self.feed_manager.register_callback(
                    self.vc_feed.fid, self._vc_feed_callback
                )
                return
            else:
                # waiting for version control feed
                return

        # new file update feed
        new_fid = self.update_feed.get_children()[-1]
        self.feed_manager.register_callback(new_fid, self._file_feed_callback)

    def _vc_feed_callback(self, _: bytes) -> None:
        """
        Handles version control commands, once they are appended.
        TODO: implement
        """
        assert self.vc_feed is not None, "version control feed not found"

        front_type = self.vc_feed.get_type(-1)
        if front_type == PacketType.ischild:
            # first packet in version control feed -> ignore
            return

        # TODO: apply updates according to version control feed
        print("version control feed change")

    def _file_feed_callback(self, fid: bytes) -> None:
        """
        Callback function that is registered to a file update feed.
        Once new packets or blobs are appended, they are handled depending
        on packet type.
        """
        feed = self.feed_manager.get_feed(fid)
        assert feed is not None, "failed to get feed"
        if feed.waiting_for_blob() is not None:
            # blob not complete
            return

        # handle differently, depending on new pkt
        front_type = feed.get_type(-1)

        if front_type == PacketType.updfile:
            # TODO: check if file exists, if not -> create new
            return

        if front_type == PacketType.mkchild:
            # setup of update feed finished, add to version control dictionary
            file_name = feed.get_upd_file_name()
            emergency_fid = feed.get_children()[0]
            self.vc_dict[file_name] = (feed.fid, emergency_fid)
            self._save_config()
            return

        if front_type == PacketType.chain20:
            # TODO: not instantly apply update
            self._apply_update(feed.get_upd_file_name(), feed[-1])

    def _apply_update(self, file_name: str, bytes_changes: bytes) -> None:
        """
        Applies the changes (encoded as bytes) to a given file.
        """
        changes = bytes_to_changes(bytes_changes)
        old_file = read_file(self.path, file_name)
        assert old_file is not None, "failed to read file"

        # apply
        new_file = apply_changes(old_file, changes)
        write_file(self.path, file_name, new_file)

    def update_file(self, file_name: str, update: str) -> None:
        """
        Computes the difference between a given file and update
        and appends the changes to the corresponding file update feed
        as a single blob.
        """
        if not self.may_update:
            print("may not append new updates")
            return

        if file_name not in self.vc_dict:
            print("file does not exist")
            # TODO: create new file
            return

        # get difference between old file and new file
        old_file = read_file(self.path, file_name)
        assert old_file is not None, "failed to read file"
        changes = get_file_changes(old_file, update)

        # append to feed
        fid, _ = self.vc_dict[file_name]
        feed = self.feed_manager.get_feed(fid)
        assert feed is not None, "failed to get feed"

        feed.append_blob(changes)
