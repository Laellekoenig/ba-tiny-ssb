import json
import os
from socket import create_server
import sys
from .feed import Feed
from .feed_manager import FeedManager
from .packet import PacketType
from .ssb_util import to_hex, create_keypair, from_hex
from .version_util import (
    apply_changes,
    changes_to_bytes,
    get_changes,
    jump_versions,
    read_file,
    write_file,
)


# non-micropython import
if sys.implementation.name != "micropython":
    # Optional type annotations are ignored in micropython
    from typing import Optional, Union


# helper lambdas
to_fid = lambda x: x if type(x) is bytes else x.fid
bytes_to_int = lambda x: x if type(x) is int else int.from_bytes(x, "big")


class VersionManager:
    """
    Manages the update feed including applying and or adding new updates to or from the feed.
    """

    cfg_file_name = "update_cfg.json"

    def __init__(self, path: str, feed_manager: FeedManager) -> None:
        self.path = path
        self.feed_manager = feed_manager

        self.vc_dict = {}  # key: file name, value: (update_fid, emergency_fid)
        self.apply_queue = {}  # updates that cannot be applied yet due to missing blobs
        self.apply_dict = {}  # key: file name, value: currently applied version number
        self._load_config()

        self.update_feed = None
        self.vc_feed = None
        self.may_update = False

    def __del__(self) -> None:
        self._save_config()

    def _save_config(self) -> None:
        """
        Saves the version control dictionary to a json file.
        """
        dictionary = {
            "vc_dict": {
                k: (to_hex(v[0]), to_hex(v[1])) for k, v in self.vc_dict.items()
            },
            "apply_queue": {to_hex(k): v for k, v in self.apply_queue.items()},
            "apply_dict": self.apply_dict,
        }

        # save as json dump
        json_str = json.dumps(dictionary)
        write_file(self.path, self.cfg_file_name, json_str)

    def _load_config(self) -> None:
        """
        Loads the configuration file containing the version control dict,
        apply queue and apply dictionary.
        The file name of a monitored file is the key and a tuple consisting
        of the corresponding file update FID and emergency FID is is the associated value.
        """
        if self.cfg_file_name not in os.listdir(self.path):
            # no config found -> empty dictionaries
            self.vc_dict = {}
            self.apply_queue = {}
            self.apply_dict = {}
        else:
            # file exists, load json
            json_str = read_file(self.path, self.cfg_file_name)
            assert json_str is not None
            str_dict = json.loads(json_str)

            # fill in
            self.vc_dict = {
                k: (from_hex(v[0]), from_hex(v[1]))
                for k, v in str_dict["vc_dict"].items()
            }

            self.apply_queue = {
                from_hex(k): int(v) for k, v in str_dict["apply_queue"].items()
            }

            self.apply_dict = str_dict["apply_dict"]

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
            vc_fid = children[0]
            self.vc_feed = self.feed_manager.get_feed(vc_fid)
            assert self.vc_feed is not None, "failed to get version control feed"

        # check if the key is available -> allowed to write new updates
        if to_hex(self.update_feed.fid) not in self.feed_manager.keys:
            self.may_update = False
            # register callbacks for update feeds
            self._register_callbacks()
            return

        # callback not needed -> manager of update feed
        self.may_update = True

        # check monitored files
        files = os.listdir(self.path)
        for f in files:
            if f not in self.vc_dict and f != self.cfg_file_name and not f[0] == ".":
                # create new update feed for file
                skey, vkey = create_keypair()
                new = self.feed_manager.create_child_feed(self.update_feed, vkey, skey)
                assert new is not None, "failed to create new file feed"
                new.add_upd_file_name(f, 1)  # add file name to feed, start at version 1

                # create emergency feed
                skey, vkey = create_keypair()
                emergency = self.feed_manager.create_child_feed(new, vkey, skey)
                assert emergency is not None, "failed to create emergency feed"

                # save to version control dictionary
                self.vc_dict[f] = (new.fid, emergency.fid)
                self.apply_dict[f] = 0  # no updates applied yet

        self._save_config()

    def _register_callbacks(self) -> None:
        """
        Registers all the necessary callback functions to the update, version
        control and file feeds.
        """
        if self.update_feed is None:
            return

        # update feed
        self.feed_manager.register_callback(
            self.update_feed.fid, self._update_feed_callback
        )

        # check for version control feed
        children = self.update_feed.get_children()
        if len(children) < 1:
            return

        self.feed_manager.register_callback(
            children[0], self._vc_feed_callback  # version control feed
        )

        # register callbacks on file feeds
        for item in self.vc_dict:
            file_fid, emergency_fid = self.vc_dict[item]

            self.feed_manager.register_callback(file_fid, self._file_feed_callback)

            self.feed_manager.register_callback(
                emergency_fid, self._emergency_feed_callback
            )

    def _update_feed_callback(self, fid: bytes) -> None:
        """
        Callback function that is registered to the main update feed.
        Updates the version control dict according to new entries.
        Also creates new file update feeds.
        """
        assert self.update_feed is not None, "no update feed set"
        assert self.update_feed.fid == fid, "not called on update feed"

        if self.update_feed.waiting_for_blob() is not None:
            return  # waiting for blob, nothing to update

        if self.vc_feed is None:
            # check if version control feed was added (first child)
            children = self.update_feed.get_children()
            if len(children) >= 1:
                self.vc_feed = self.feed_manager.get_feed(children[0])
                assert self.vc_feed is not None, "failed to get feed"
                # register callback
                self.feed_manager.register_callback(
                    self.vc_feed.fid, self._vc_feed_callback
                )
                return
            else:
                return  # waiting for version control feed

        # new file update feed
        new_fid = self.update_feed.get_children()[-1]
        self.feed_manager.register_callback(new_fid, self._file_feed_callback)

    def _vc_feed_callback(self, _: bytes) -> None:
        """
        Handles version control commands once they are appended.
        """
        assert self.vc_feed is not None, "version control feed not found"

        front_type = self.vc_feed.get_type(-1)
        if front_type == PacketType.ischild:
            return  # first packet in version control feed -> ignore

        if front_type == PacketType.applyup:
            print("applying update")
            pkt = self.vc_feed[-1]
            fid, seq = pkt[:32], pkt[32:36]
            self._apply_update(fid, seq)

    def _file_feed_callback(self, fid: bytes) -> None:
        """
        Callback function that is registered to a file update feed.
        Once new packets or blobs are appended, they are handled depending on packet type.
        """
        feed = self.feed_manager.get_feed(fid)
        assert feed is not None, "failed to get feed"

        if feed.waiting_for_blob() is not None:
            return  # blob not complete

        # handle depending on newly appended packet type
        front_type = feed.get_type(-1)

        if front_type == PacketType.chain20:
            # new update arrived
            if fid in self.apply_queue:
                # check if waiting to apply update
                seq = self.apply_queue[fid]
                self._apply_update(fid, seq)

        if front_type == PacketType.mkchild:
            # setup of update feed finished, add to version control dictionary
            file_name = feed.get_upd_file_name()
            emergency_fid = feed.get_children()[0]

            # register emergency callback
            self.feed_manager.register_callback(
                emergency_fid, self._emergency_feed_callback
            )

            # add to version control dict
            self.vc_dict[file_name] = (feed.fid, emergency_fid)

            # add current apply info if it does not exists
            if file_name not in self.apply_dict:
                self.apply_dict[file_name] = 0
            self._save_config()
            return

        if front_type == PacketType.updfile:
            file_name = feed.get_upd_file_name()
            assert file_name is not None
            # create file if it does not exist
            if file_name not in os.listdir(self.path):
                write_file(self.path, file_name, "")

    def _emergency_feed_callback(self, fid: bytes) -> None:
        """
        Handles emergency updates. Removes the callback function
        from the old file feed and adds it to the old emergency feed.
        """
        feed = self.feed_manager.get_feed(fid)
        assert feed is not None, "failed to get feed"

        if feed.waiting_for_blob() is not None:
            return  # wait for completion of blob

        front_type = feed.get_type(-1)

        if front_type == PacketType.mkchild:
            # new emergency update incoming
            parent_fid = feed.get_parent()
            assert parent_fid is not None, "failed to find parent"

            # remove callback from old feeds
            self.feed_manager.remove_callback(parent_fid, self._file_feed_callback)
            self.feed_manager.remove_callback(feed.fid, self._emergency_feed_callback)

            # add callback to new feeds
            self.feed_manager.register_callback(feed.fid, self._file_feed_callback)
            emergency_fid = feed.get_children()[0]
            self.feed_manager.register_callback(
                emergency_fid, self._emergency_feed_callback
            )

            # update version control dictionary
            file_name = feed.get_upd_file_name()
            self.vc_dict[file_name] = (feed.fid, emergency_fid)
            self._save_config()

    def _apply_update(self, fid: Union[bytes, Feed], seq: Union[int, bytes]) -> None:
        """
        Applies the changes (encoded as bytes) to a given file.
        """
        assert self.vc_feed is not None

        # convert
        fid = to_fid(fid)
        seq = bytes_to_int(seq)
        assert type(fid) is bytes and type(seq) is int, "conversions failed"

        file_feed = self.feed_manager.get_feed(fid)
        if file_feed is None:
            print("waiting for feed")

            if fid in self.apply_queue and self.apply_queue[fid] == seq:
                return  # already in queue

            self.apply_queue[fid] = seq
            self._save_config()
            return

        # check if update already available
        current_version_num = file_feed.get_current_version_num()
        if current_version_num is None or current_version_num < seq:
            print("waiting for update")

            if fid in self.apply_queue and self.apply_queue[fid] == seq:
                return  # already in queue

            self.apply_queue[fid] = seq
            self._save_config()
            return

        # check if blob is complete
        if file_feed.get_current_version_num() == seq and file_feed.waiting_for_blob():
            print("waiting for blob")

            if fid in self.apply_queue and self.apply_queue[fid] == seq:
                return  # already in queue

            self.apply_queue[fid] = seq
            self._save_config()
            return

        print(f"applying {seq}")

        # get content from current file
        file_name = file_feed.get_upd_file_name()
        assert file_name is not None
        file = read_file(self.path, file_name)
        assert file is not None, "failed to read file"

        current_apply = self.apply_dict[file_name]
        if seq == current_apply:
            return  # already applied version (should not happen)

        # compute changes from update and apply them to file
        changes = jump_versions(current_apply, seq, file_feed, self.feed_manager)
        file = apply_changes(file, changes)

        # save updated file
        write_file(self.path, file_name, file)
        if fid in self.apply_queue:
            del self.apply_queue[fid]
        self.apply_dict[file_name] = seq
        self._save_config()

    def update_file(
        self, file_name: str, update: str, depends_on: int
    ) -> Optional[int]:
        """
        Computes the difference between a given file and update
        and appends the changes to the corresponding file update feed as a single blob.
        Returns the fid and sequence number of the update, so it can be applied later.
        """
        assert self.vc_feed is not None

        if not self.may_update:
            print("may not append new updates")
            return

        if file_name not in self.vc_dict:
            print("file does not exist")
            # TODO: create new file
            return None

        # get feed
        fid, _ = self.vc_dict[file_name]
        feed = self.feed_manager.get_feed(fid)
        assert feed is not None, "failed to get feed"

        # get currently applied version and version number
        current_file = read_file(self.path, file_name)
        assert current_file is not None, "failed to read file"
        # current_apply = self.vc_feed.get_newest_apply(fid)
        current_apply = self.apply_dict[file_name]

        # check version numbers
        current_v = feed.get_current_version_num()
        assert current_v is not None, "failed to get current version number"

        # translate possible negative index of dependency
        if depends_on < 0:
            # -1 => latest update
            depends_on = current_v + depends_on + 1

        if depends_on > current_v:
            print("dependency does not exist yet")
            return None

        # get changes
        changes = jump_versions(current_apply, depends_on, feed, self.feed_manager)
        current_file = apply_changes(current_file, changes)

        # now calculate difference
        update_changes = get_changes(current_file, update)

        # append to feed
        feed.append_blob(changes_to_bytes(update_changes, depends_on))

        # return update info
        return feed.get_current_version_num()

    def emergency_update_file(
        self, file_name: str, update: str, depends_on: int
    ) -> Optional[int]:
        """
        Computes the difference between a given file and update and appends the
        changes to the corresponding emergency file update feed as a single blob.
        This makes the emergency feed the new main feed and a new emergency feed is created.
        """
        assert self.vc_feed is not None, "need vc feed to update"

        if not self.may_update:
            print("may not append new updates")
            return

        if file_name not in self.vc_dict:
            return

        # get feeds
        fid, emergency_fid = self.vc_dict[file_name]
        feed = self.feed_manager.get_feed(fid)
        emergency_feed = self.feed_manager.get_feed(emergency_fid)
        assert feed is not None and emergency_feed is not None, "failed to get feeds"

        # check dependency version number
        current_v = feed.get_current_version_num()
        assert current_v is not None, "failed to get current version number"

        # translate possible negative index of dependency
        if depends_on < 0:
            depends_on = current_v + depends_on + 1

        # check dependency
        if depends_on > current_v:
            print("dependency does not exist yet")
            return None

        # get current file and apply
        current_file = read_file(self.path, file_name)
        assert current_file is not None, "failed to read file"
        current_apply = self.apply_dict[file_name]

        # change current file to dependency
        changes = jump_versions(current_apply, depends_on, feed, self.feed_manager)
        current_file = apply_changes(current_file, changes)

        # calculate update differences
        update_changes = get_changes(current_file, update)

        # update emergency feed info
        # continue version count where parent stopped
        new_v = current_v + 1
        emergency_feed.add_upd_file_name(file_name, new_v)

        # add new emergency feed
        skey, vkey = create_keypair()
        new_emergency = self.feed_manager.create_child_feed(emergency_feed, vkey, skey)
        assert new_emergency is not None, "failed to create new feed"

        # add update to old emergency feed
        emergency_feed.append_blob(changes_to_bytes(update_changes, depends_on))

        # add apply to version control feed
        self.vc_feed.add_apply(emergency_feed.fid, new_v)

        # apply changes locally
        updated_file = apply_changes(current_file, update_changes)
        write_file(self.path, file_name, updated_file)

        # update information in version control feed
        self.vc_dict[file_name] = (emergency_feed.fid, new_emergency.fid)
        self.apply_dict[file_name] = new_v
        self._save_config()

        return new_v

    def add_apply(self, file_name: str, v_num: int) -> bool:
        """
        Adds a packet of type applyup to the version control feed, containing
        the version number of the update that should be applied.
        The local file is changes to the one determined by the version number.
        """
        assert self.vc_feed is not None, "no version control feed present"

        if not self.may_update:
            print("may not apply updates")
            return False

        if file_name not in self.vc_dict:
            print("file not found")
            return False

        # get file update feed
        fid, _ = self.vc_dict[file_name]
        feed = self.feed_manager.get_feed(fid)
        assert feed is not None, "failed to get feed"

        # convert negative indices
        current_version_num = feed.get_current_version_num()
        assert current_version_num is not None, "failed to get current version number"
        if v_num < 0:
            v_num = current_version_num + v_num + 1

        # can't apply update that does not exist yet
        if current_version_num < v_num:
            print("update does not exist yet")
            return False

        # add to version control feed and apply locally
        self.vc_feed.add_apply(fid, v_num)
        self._apply_update(fid, v_num)

        return True

    def create_new_file(self, file_name: str) -> None:
        assert self.update_feed is not None
        print("creating new file: {}".format(file_name))

        if file_name in os.listdir(self.path):
            print("file already exists")
            return

        write_file(self.path, file_name, "")

        # create new feed
        skey, vkey = create_keypair()
        feed = self.feed_manager.create_child_feed(self.update_feed, vkey, skey)
        assert feed is not None
        feed.add_upd_file_name(file_name, 1)

        # create emergency feed
        skey, vkey = create_keypair()
        emergency = self.feed_manager.create_child_feed(feed, vkey, skey)
        assert emergency is not None

        # add to config
        self.vc_dict[file_name] = (feed.fid, emergency.fid)
        self.apply_dict[file_name] = 0
        self._save_config()
