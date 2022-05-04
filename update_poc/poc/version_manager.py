import json
import os
import sys
from .version_util import (
    apply_changes,
    changes_to_bytes,
    get_changes,
    jump_versions,
    read_file,
    write_file,
)
from tinyssb.feed import Feed
from tinyssb.feed_manager import FeedManager
from tinyssb.packet import PacketType
from tinyssb.ssb_util import to_hex, create_keypair, from_hex

# non-micropython import
if sys.implementation.name != "micropython":
    # Optional type annotations are ignored in micropython
    from typing import Optional, Union


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

        self.apply_queue = {}

    def __del__(self) -> None:
        self._save_config()

    def _load_config(self) -> None:
        """
        Loads the configuration file containing the version control dict.
        The file name of a monitored file is the key and a tuple consisting
        of the corresponding file update FID and emergency FID is is the
        associated value.
        """
        if self.cfg_file_name not in os.listdir(self.path):
            # no config found -> empty dict
            self.vc_dict = {}
            self.apply_queue = {}
        else:
            # file exists
            json_str = read_file(self.path, self.cfg_file_name)
            assert json_str is not None
            str_dict = json.loads(json_str)
            self.vc_dict = {
                k: (from_hex(v[0]), from_hex(v[1]))
                for k, v in str_dict["vc_dict"].items()
            }
            self.apply_queue = {
                from_hex(k): int(v) for k, v in str_dict["apply_queue"].items()
            }

    def _save_config(self) -> None:
        """
        Saves the version control dictionary to a json file.
        """
        dictionary = {
            "vc_dict": {
                k: (to_hex(v[0]), to_hex(v[1])) for k, v in self.vc_dict.items()
            },
            "apply_queue": {to_hex(k): v for k, v in self.apply_queue.items()},
        }
        json_str = json.dumps(dictionary)
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
            vc_fid = children[0]
            self.vc_feed = self.feed_manager.get_feed(vc_fid)
            assert self.vc_feed is not None, "failed to get version control feed"

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
            if f not in self.vc_dict and f != self.cfg_file_name and not f[0] == ".":
                print(f)
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
        """
        assert self.vc_feed is not None, "version control feed not found"

        front_type = self.vc_feed.get_type(-1)
        if front_type == PacketType.ischild:
            # first packet in version control feed -> ignore
            return

        if front_type == PacketType.applyup:
            print("applying update")
            pkt = self.vc_feed[-1]
            fid, seq = pkt[:32], pkt[32:36]
            self._apply_update(fid, seq)

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

            # register emergency callback
            self.feed_manager.register_callback(
                emergency_fid, self._emergency_feed_callback
            )

            # add to version control dict
            self.vc_dict[file_name] = (feed.fid, emergency_fid)
            self._save_config()
            return

        if front_type == PacketType.chain20:
            # check if has entry in queued updates
            if fid in self.apply_queue:
                seq = self.apply_queue[fid]
                self.apply_queue.pop(fid, None)
                self._apply_update(fid, seq)

    def _emergency_feed_callback(self, fid: bytes) -> None:
        """
        Handles emergency updates. Removes the callback function
        for the old file feed and adds it to the old emergency feed.
        """
        feed = self.feed_manager.get_feed(fid)
        assert feed is not None, "failed to get feed"
        if feed.waiting_for_blob() is not None:
            # wait for completion of blob
            return

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
        if type(fid) is Feed:
            fid = fid.fid
        assert type(fid) is bytes

        if type(seq) is bytes:
            seq = int.from_bytes(seq, "big")
        assert type(seq) is int

        file_feed = self.feed_manager.get_feed(fid)
        assert file_feed is not None

        # check if update already available
        if file_feed.get_current_version_num() < seq:
            self.apply_queue[fid] = seq
            self._save_config()
            return

        print(f"applying {seq}")

        # go backwards or forwards?
        current_apply = self.vc_feed.get_newest_apply(file_feed.fid)
        if seq == current_apply:
            self._save_config()
            return

        # get content from current file
        file_name = file_feed.get_upd_file_name()
        assert file_name is not None
        file = read_file(self.path, file_name)
        assert file is not None, "failed to read file"

        changes = jump_versions(current_apply, seq, file_feed, self.feed_manager)
        file = apply_changes(file, changes)

        # save updated file
        write_file(self.path, file_name, file)
        self._save_config()

    def update_file(
        self, file_name: str, update: str, depends_on: int
    ) -> Optional[int]:
        """
        Computes the difference between a given file and update
        and appends the changes to the corresponding file update feed
        as a single blob.
        Returns the fid and sequence number of the update, so it can be applied
        later.
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
        current_apply = self.vc_feed.get_newest_apply(fid)

        # check version numbers
        current_v = feed.get_current_version_num()

        # translate possible negative index of dependency
        if depends_on < 0:
            # -1 => latest update
            depends_on = current_v + depends_on + 1

        if depends_on > current_v:
            print("dependency does not exist yet")
            return None

        # get changes
        # TODO: dependency in parent
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
        Computes the difference between a given file and update
        and appends the changes to the corresponding emergency file update
        feed as a single blob.
        This makes the emergency feed the new main feed and a new emergency
        feed is created.
        """
        assert self.vc_feed is not None, "need vc feed to update"
        if not self.may_update:
            print("may not append new updates")
            return

        if file_name not in self.vc_dict:
            return

        # get feed
        fid, emergency_fid = self.vc_dict[file_name]
        feed = self.feed_manager.get_feed(fid)
        assert feed is not None, "failed to get feed"
        emergency_feed = self.feed_manager.get_feed(emergency_fid)
        assert emergency_feed is not None, "failed to get feed"

        # check dependency version number
        current_v = feed.get_current_version_num()

        # translate possible negative index of dependency
        if depends_on < 0:
            depends_on = current_v + depends_on + 1

        # check dependency
        if depends_on > current_v:
            print("dependency does not exist yet")
            return None

        # get current file
        current_file = read_file(self.path, file_name)
        assert current_file is not None, "failed to read file"
        current_apply = self.vc_feed.get_newest_apply(feed.fid)

        # change current file to dependency
        # TODO: dependency in parent
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
        self._save_config()

        return new_v

    def add_apply(self, file_name: str, seq: int) -> bool:
        assert self.vc_feed is not None, "no version control feed present"
        if file_name not in self.vc_dict:
            print("file not found")
            return False

        # locally apply update
        fid, _ = self.vc_dict[file_name]
        feed = self.feed_manager.get_feed(fid)
        assert feed is not None, "failed to get feed"

        # convert negative indices
        if seq < 0:
            seq = feed.get_current_version_num() + seq + 1

        # can't apply update that does not exist yet
        if feed.get_current_version_num() < seq:
            print("update does not exist yet")
            return False

        self._apply_update(fid, seq)

        # add to version control feed
        self.vc_feed.add_apply(fid, seq)

        return True
