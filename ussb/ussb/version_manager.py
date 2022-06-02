from .feed import (
    FEED,
    add_apply,
    add_upd,
    create_child_feed,
    get_children,
    get_dependency,
    get_feed,
    get_parent,
    get_payload,
    get_upd,
    get_wire,
    length,
    waiting_for_blob,
)
from .feed_manager import FeedManager
from .packet import (
    APPLYUP,
    CHAIN20,
    ISCHILD,
    MKCHILD,
    UPDFILE,
    to_var_int,
)
from .util import listdir, walk, create_dirs_and_file, PYCOM, from_var_int
from _thread import allocate_lock
from json import dumps, loads
from sys import implementation
from ubinascii import hexlify, unhexlify
from uctypes import struct


# helps with debugging in vim
if implementation.name != "micropython":
    from typing import List, Tuple, Dict, Callable, Optional


class VersionManager:
    """
    Responsible for managing, applying and reverting updates.
    """

    __slots__ = (
        "_update_next",
        "apply_dict",
        "apply_queue",
        "feed_manager",
        "may_update",
        "update_fid",
        "update_lock",
        "vc_dict",
        "vc_fid",
    )

    def __init__(self, feed_manager: FeedManager):
        self.feed_manager = feed_manager
        self.vc_dict = {}
        self.apply_queue = {}
        self.apply_dict = {}
        self.update_fid = None
        self.vc_fid = None
        self.update_lock = allocate_lock()
        self._update_next = []
        self._load_config()

        if self.update_fid and bytes(self.update_fid) in self.feed_manager.keys:
            self.may_update = True
        else:
            self.may_update = False

        self._register_callbacks()

    def __del__(self) -> None:
        self._save_config()

    def _save_config(self) -> None:
        """
        Saves the vc_dict, apply_queue, apply_dict, update_fid and update_next
        to a json file.
        """
        if self.update_fid is None:
            return

        cfg = {
            "vc_dict": {
                k: (hexlify(v[0]).decode(), hexlify(v[1]).decode())
                for k, v in self.vc_dict.items()
            },
            "apply_queue": {
                hexlify(bytes(k)).decode(): v for k, v in self.apply_queue.items()
            },
            "apply_dict": self.apply_dict,
            "update_fid": hexlify(self.update_fid).decode(),
            "update_next": [(hexlify(x).decode(), y) for x, y in self._update_next],
        }

        f = open("update_cfg.json", "w")
        f.write(dumps(cfg))
        f.close()

    def _load_config(self) -> None:
        """
        Loads the content of the saved json file into this instance.
        If the file does not exist, empty default values are used.
        """
        fn = "update_cfg.json"
        if fn not in listdir():
            self.vc_dict = {}
            self.apply_queue = {}
            self.apply_dict = {}
            return

        f = open(fn)
        cfg = loads(f.read())
        f.close()

        self.vc_dict = {
            k: (
                bytearray(unhexlify(v[0].encode())),
                bytearray(unhexlify(v[1].encode())),
            )
            for k, v in cfg["vc_dict"].items()
        }

        self.apply_queue = {
            unhexlify(k.encode()): v for k, v in cfg["apply_queue"].items()
        }

        self.apply_dict = cfg["apply_dict"]
        self.update_fid = unhexlify((cfg["update_fid"]).encode())
        self._update_next = [(unhexlify(x.encode()), y) for x, y in cfg["update_next"]]

        # check for version control feed in update feed (first child)
        children = get_children(get_feed(self.update_fid))
        if len(children) > 1:
            vc_fid = children[0]
            assert type(vc_fid) is bytearray
            self.vc_fid = vc_fid

    def is_configured(self) -> bool:
        """
        Returns True if the update feed ID was added to the version manager.
        """
        return self.update_fid is not None

    def set_update_feed(self, update_fid: bytearray) -> None:
        """
        Sets the given feed as the update feed of the version manager.
        This is also saved to a json file.
        """
        self.update_fid = update_fid

        feed = get_feed(update_fid)

        # check for version control feed
        children = get_children(feed)
        if len(children) >= 1:
            vc_fid = children[0]
            assert type(vc_fid) is bytearray
            self.vc_fid = vc_fid

        # check if is authorized to append new updates
        if bytes(update_fid) not in self.feed_manager.keys:
            self.may_update = False
            self._register_callbacks()
            return

        # callbacks not needed -> manager of update feed
        self.may_update = True

        # search for files to monitor
        files = walk()
        for f in files:
            # ignore certain file formats and already monitored files
            if (
                f not in self.vc_dict
                and not f[0] == "."
                and not f.endswith(".log")
                and not f.endswith(".json")
                and not f.endswith(".head")
            ):

                # create update and emergency update of file
                update_key = self.feed_manager.get_key(update_fid)
                assert update_key is not None

                # create new update feed for file
                ckey, cfid = self.feed_manager.generate_keypair()
                new = create_child_feed(feed, update_key, cfid, ckey)
                assert new is not None, "failed to create new file feed"
                add_upd(new, f, ckey)

                # create emergency feed
                ekey, efid = self.feed_manager.generate_keypair()
                emergency = create_child_feed(new, ckey, efid, ekey)
                assert emergency is not None, "failed to create emergency feed"

                # save to version control dictionary
                self.vc_dict[f] = (cfid, efid)
                print(f, "---", hexlify(cfid).decode())
                self.apply_dict[f] = 0  # no updates applied yet
                self._save_config()

    def _register_callbacks(self) -> None:
        """
        Registers callback functions to all monitored file update feeds.
        These are executed in the feed manager, once new packets/blobs are appended.
        """
        if self.update_fid is None:
            return

        # update feed
        print("-> registering update feed callback")
        self.feed_manager.register_callback(self.update_fid, self._update_feed_callback)

        # check for version control feed
        children = get_children(get_feed(self.update_fid))
        if len(children) < 1:
            return

        vc_fid = children[0]
        assert type(vc_fid) is bytearray

        print("-> registering VC feed callback")
        self.feed_manager.register_callback(
            vc_fid, self._vc_feed_callback  # version control feed
        )

        # register callbacks on file feeds
        for _, (file_fid, emergency_fid) in self.vc_dict.items():
            print("-> registering file feed callbacks")
            self.feed_manager.register_callback(file_fid, self._file_feed_callback)
            self.feed_manager.register_callback(
                emergency_fid, self._emergency_feed_callback
            )

    def _update_feed_callback(self, fid: bytearray) -> None:
        """
        Callback function of the main update feed.
        Handles new version control feed and new file update feeds.
        """
        assert self.update_fid is not None, "no update feed set"
        assert self.update_fid == fid, "not called on update feed"

        children = get_children(get_feed(self.update_fid))

        if self.vc_fid is None:
            # check if version control feed was added (first child)
            if len(children) >= 1:
                vc_fid = children[0]
                assert type(vc_fid) is bytearray
                self.vc_fid = vc_fid
                # register callback
                self.feed_manager.register_callback(self.vc_fid, self._vc_feed_callback)
                return
            else:
                return  # waiting for version control feed

        # new file update feed
        new_fid = children[-1]
        assert type(new_fid) is bytearray
        self.feed_manager.register_callback(new_fid, self._file_feed_callback)

    def _vc_feed_callback(self, fid: bytearray) -> None:
        """
        Callback function of the version control feed.
        Handles new APPLYUP packets.
        """
        assert self.vc_fid is not None, "version control feed not found"

        # get newly appended packet
        front_type = get_wire(get_feed(self.vc_fid), -1)[15:16]

        if front_type == ISCHILD.to_bytes(1, "big"):
            return  # first packet in version control feed -> ignore

        if front_type == APPLYUP.to_bytes(1, "big"):
            # apply new update
            payload = get_payload(get_feed(self.vc_fid), -1)
            fid, seq = payload[:32], payload[32:36]

            # add to a queue, bodge to fix PYCOM stack overflows
            if PYCOM:
                with self.update_lock:
                    self._update_next.append((fid, seq))
            else:
                self._apply_update(fid, seq)

    def _file_feed_callback(self, fid: bytearray) -> None:
        """
        Callback function for file update feeds.
        Handles newly appended update blobs.
        """
        feed = get_feed(fid)
        assert feed is not None, "failed to get feed"

        if waiting_for_blob(feed) is not None:
            return  # blob not complete

        # handle depending on newly appended packet
        front_type = get_wire(feed, -1)[15:16]

        if front_type == CHAIN20.to_bytes(1, "big"):
            # new update arrived
            b_fid = bytes(fid)
            if bytes(b_fid) in self.apply_queue:
                # check if waiting to apply update
                seq = self.apply_queue[b_fid]

                # pycom bodge, fix stack overflows
                if PYCOM:
                    with self.update_lock:
                        self._update_next.append((fid, seq.to_bytes(4, "big")))
                else:
                    self._apply_update(fid, seq.to_bytes(4, "big"))

        if front_type == MKCHILD.to_bytes(1, "big"):
            # setup of update feed finished, add to version control dictionary
            fn_v_tuple = get_upd(feed)
            assert fn_v_tuple is not None
            file_name, version = fn_v_tuple
            del fn_v_tuple

            emergency_fid = get_children(feed)[0]
            assert type(emergency_fid) is bytearray

            # register emergency callback
            self.feed_manager.register_callback(
                emergency_fid, self._emergency_feed_callback
            )

            # add to version control dict
            self.vc_dict[file_name] = (fid, emergency_fid)

            # add current apply info if it does not exists
            if file_name not in self.apply_dict:
                self.apply_dict[file_name] = version
            self._save_config()
            return

        if front_type == UPDFILE.to_bytes(1, "big"):
            # new file or activation of emergency feed
            fn_v_tuple = get_upd(feed)
            assert fn_v_tuple is not None

            file_name, _ = fn_v_tuple

            # create file if it does not exist
            if file_name not in walk():
                print("creating new file")

                # create file and directories if necessary
                create_dirs_and_file(file_name)

    def _emergency_feed_callback(self, fid: bytearray) -> None:
        """
        Callback function of file update emergency feeds.
        Handles activation of emergency feeds.
        """
        feed = get_feed(fid)
        assert feed is not None, "failed to get feed"

        if waiting_for_blob(feed) is not None:
            return  # wait for completion of blob

        front_type = get_wire(feed, -1)[15:16]

        if front_type == MKCHILD.to_bytes(1, "big"):
            print("switching to emergency feed")
            # new emergency update incoming
            parent_fid = get_parent(feed)
            assert parent_fid is not None, "failed to find parent"

            # remove callback from old feeds
            self.feed_manager.remove_callbacks(parent_fid)
            self.feed_manager.remove_callbacks(fid)

            # add callback to new feeds
            self.feed_manager.register_callback(fid, self._file_feed_callback)
            emergency_fid = get_children(feed)[0]
            assert type(emergency_fid) is bytearray
            self.feed_manager.register_callback(
                emergency_fid, self._emergency_feed_callback
            )

            # update version control dictionary
            fn_v_tuple = get_upd(feed)
            assert fn_v_tuple is not None
            file_name, _ = fn_v_tuple
            del fn_v_tuple

            del self.vc_dict[file_name]
            self.vc_dict[file_name] = (fid, emergency_fid)
            self._save_config()

    def _apply_update(self, fid: bytearray, seq: bytearray) -> None:
        """
        Applies the given version number of the file, monitored by the feed
        with the given feed ID.
        """
        assert self.vc_fid is not None

        # convert bytes to int
        int_seq = int.from_bytes(seq, "big")
        del seq

        try:
            file_feed = get_feed(fid)
        except Exception:
            file_feed = None

        if file_feed is None:
            print("waiting for feed")

            # add to apply queue
            b_fid = bytes(fid)
            if b_fid in self.apply_queue and self.apply_queue[b_fid] == int_seq:
                return  # already in queue

            self.apply_queue[b_fid] = int_seq
            self._save_config()
            return

        # assuming that only updates are appended, faster than iterating over entire feed
        num_updates = length(file_feed) - 3  # subtract ICH UPD and MKC entries
        if num_updates <= 0:
            print("waiting for UPD packet")
            # add to apply queue
            self.apply_queue[bytes(fid)] = int_seq
            self._save_config()
            return

        # get file name and base version number
        fn_v_tuple = get_upd(file_feed)
        # FIXME: can this lead to an error?
        assert fn_v_tuple is not None
        file_name, base_version = fn_v_tuple
        newest_version = num_updates + base_version

        if newest_version < int_seq:
            print("waiting for update")
            # add to apply queue
            b_fid = bytes(fid)
            if b_fid in self.apply_queue and self.apply_queue[b_fid] == int_seq:
                return

            self.apply_queue[b_fid] = int_seq
            self._save_config()
            return

        if newest_version == int_seq and waiting_for_blob(file_feed):
            # add to apply queue
            print("waiting for blob")
            b_fid = bytes(fid)
            if b_fid in self.apply_queue and self.apply_queue[b_fid] == int_seq:
                return  # already in queue

            self.apply_queue[b_fid] = int_seq
            self._save_config()
            return

        # nothing missing -> apply update
        print("applying {}".format(int_seq))

        # get current version
        f = open(file_name)
        content = f.read()
        f.close()

        current_apply = self.apply_dict[file_name]
        if int_seq == current_apply:
            return

        # compute changes and apply them
        new_content = jump_versions(content, current_apply, int_seq, file_feed)
        del content

        # save updated file
        f = open(file_name, "w")
        f.write(new_content)
        f.close()

        # remove from apply queue
        b_fid = bytes(fid)
        if b_fid in self.apply_queue:
            del self.apply_queue[b_fid]

        # update information in apply dict
        self.apply_dict[file_name] = int_seq
        self._save_config()

    def update_file(
        self, file_name: str, changes: List[List], dep: int
    ) -> None:  # inner list contains: index, I/D, content
        """
        Adds a blob containing the update changes and dependency to the corresponding
        file update feed.
        """
        assert self.vc_fid is not None

        if not self.may_update:
            print("may not append new updates")
            return

        if file_name not in self.vc_dict:
            print("file does not exist")
            return None

        if dep < 0:
            print("invalid dependency")
            return None

        fid, _ = self.vc_dict[file_name]
        feed = get_feed(fid)
        assert feed is not None, "failed to get feed"

        fn_v_tuple = get_upd(feed)
        assert fn_v_tuple is not None
        _, base_version = fn_v_tuple
        current_v = length(feed) - 3 + base_version

        if dep > current_v:
            print("dependency does not exist yet")
            return None

        # append update to feed
        self.feed_manager.append_blob_to_feed(feed, changes_to_bytes(changes, dep))

    def emergency_update_file(
        self, file_name: str, changes: List[List], depends_on: int
    ) -> Optional[int]:
        """
        Activates the file's emergency feed.
        Appends and applies the update changes.
        """
        assert self.vc_fid is not None, "need vc feed to update"

        if not self.may_update:
            print("may not append new updates")
            return

        if file_name not in self.vc_dict:
            print("file does not exist")
            return

        # get emergency feed and corresponding key
        old_fid, emgcy_fid = self.vc_dict[file_name]
        old_feed = get_feed(old_fid)
        emgcy_feed = get_feed(emgcy_fid)
        ekey = self.feed_manager.get_key(emgcy_fid)
        assert ekey is not None

        # get newest update number of old feed
        fn_v_tuple = get_upd(old_feed)
        assert fn_v_tuple is not None
        _, base_version = fn_v_tuple
        maxv = base_version + length(old_feed) - 3

        # remove callback from old feed
        self.feed_manager.remove_callbacks(old_fid)
        del old_fid, old_feed, fn_v_tuple

        # add UPDFILE packet to emergency feed, making it the new update feed
        add_upd(emgcy_feed, file_name, ekey, maxv)

        # create a new emergency feed
        nkey, nfid = self.feed_manager.generate_keypair()
        _ = create_child_feed(emgcy_feed, ekey, nfid, nkey)

        # update info in version control dict
        self.vc_dict[file_name] = (emgcy_fid, nfid)
        self._save_config()

        # now add update
        self.update_file(file_name, changes, depends_on)
        # and apply
        self.add_apply(file_name, -1)  # apply latest update

        # update callbacks
        self.feed_manager.remove_callbacks(emgcy_fid)
        self.feed_manager.register_callback(emgcy_fid, self._file_feed_callback)
        self.feed_manager.register_callback(nfid, self._emergency_feed_callback)

    def add_apply(self, file_name: str, v_num: int) -> None:
        """
        Adds a packet of type APPLYUP containing the file name and version number
        of the update that should be applied to the version control feed.
        Also applies the update locally.
        """
        assert self.vc_fid is not None, "no version control feed present"

        if not self.may_update:
            print("may not apply updates")
            return

        if file_name not in self.vc_dict:
            print("file not found")
            return

        # get file update feed
        fid, _ = self.vc_dict[file_name]
        feed = get_feed(fid)

        # check version numbers
        fn_v_tuple = get_upd(feed)
        assert fn_v_tuple is not None
        _, base_version = fn_v_tuple
        current_version_num = base_version + length(feed) - 3

        if v_num < 0:
            v_num += current_version_num + 1

        # can't apply update that does not exist yet
        if current_version_num < v_num:
            print("update does not exist yet")
            return

        # add to version control feed and apply locally
        key = self.feed_manager.keys[bytes(self.vc_fid)]
        self._apply_update(fid, bytearray(v_num.to_bytes(4, "big")))
        add_apply(get_feed(self.vc_fid), fid, v_num, key)

    def execute_updates(self) -> None:
        """
        Bodge to fix stack overflows on pycom devices.
        Only used on pycom devices.
        """
        with self.update_lock:
            # only keep newest apply for each file
            fid_dict = {}

            while self._update_next:
                fid, seq = self._update_next.pop(0)
                b_fid = bytes(fid)  # bytearray can't be key of a dict
                if b_fid in fid_dict:
                    other_seq = fid_dict[b_fid]
                    if other_seq < seq:
                        fid_dict[b_fid] = seq
                else:
                    fid_dict[b_fid] = seq

            # now apply updates
            for b_fid in fid_dict:
                seq = fid_dict[b_fid]
                self._apply_update(bytearray(b_fid), seq)

            self._save_config()

    def create_new_file(self, file_name: str) -> None:
        """
        Creates a new and empty file and adds it to the monitored files.
        Can only be called on the master node.
        """
        assert self.update_fid is not None
        print("creating new file: {}".format(file_name))

        if file_name in walk():
            print("file already exists")
            return

        create_dirs_and_file(file_name)

        # create new file update feed
        ckey, cfid = self.feed_manager.generate_keypair()
        ukey = self.feed_manager.get_key(self.update_fid)
        assert ukey is not None
        feed = create_child_feed(get_feed(self.update_fid), ukey, cfid, ckey)
        assert feed is not None
        add_upd(feed, file_name, ckey)

        # create emergency feed
        ekey, efid = self.feed_manager.generate_keypair()
        emergency = create_child_feed(feed, ckey, efid, ekey)
        assert emergency is not None

        # add to config
        self.vc_dict[file_name] = (cfid, efid)
        self.apply_dict[file_name] = 0
        self._save_config()

        # update dmx values
        # FIXME: only add dmx values of new feeds
        self.feed_manager._fill_dmx()


# ------------------------------------UTIL--------------------------------------
def apply_changes(content: str, changes: List[List]) -> str:
    """
    Applies the changes described by the list of changes (in order) to the given
    string and returns the resulting updated string.
    """
    ins = [c for c in changes if c[1] == "I"]
    dels = [c for c in changes if c[1] == "D"]
    dels.reverse()  # start deleting from the back, so the indexes are not messed up

    for change in dels:
        idx = change[0]
        string = change[2]

        # delete
        content = content[:idx] + content[idx + len(string) :]

    for change in ins:
        idx = change[0]
        string = change[2]

        # insert
        content = content[:idx] + string + content[idx:]

    return content


def jump_versions(content: str, start: int, end: int, feed: struct[FEED]) -> str:
    """
    Computes the changes between the starting and ending versions.
    Applies these changes to the given string and returns the updated result.
    Also needs the corresponding file update feed instance.
    """
    if start == end:
        return content  # nothing changes

    # get dependency tree
    graph, access_dict = extract_version_graph(feed)
    max_version = max([x for x, _ in access_dict.items()])

    if start > max_version or end > max_version:
        print("update not available yet")
        return content

    # do BFS on graph
    update_path = _bfs(graph, start, end)

    # three different types of paths:
    # [1, 2, 3, 4] -> only apply: 1 already applied, apply 2, 3, 4
    # [4, 3, 2, 1] -> only revert: revert 4, 3, 2 to get to version 1
    # [2, 1, 3, 4] -> revert first, then apply: revert 2, apply 3, 4
    # [1, 2, 1, 3] -> does not exist (not shortest path)
    mono_inc = lambda lst: all(x < y for x, y in zip(lst, lst[1:]))
    mono_dec = lambda lst: all(x > y for x, y in zip(lst, lst[1:]))

    if mono_inc(update_path):
        # apply all updates, ignore first
        update_path.pop(0)
        for step in update_path:
            access_feed, minv = access_dict[step]
            update_payload = get_payload(access_feed, step - minv + 3)
            changes, _ = bytes_to_changes(update_payload)
            content = apply_changes(content, changes)

    elif mono_dec(update_path):
        # revert all updates, ignore last
        update_path.pop()
        for step in update_path:
            access_feed, minv = access_dict[step]
            update_payload = get_payload(access_feed, step - minv + 3)
            changes, _ = bytes_to_changes(update_payload)
            content = apply_changes(content, reverse_changes(changes))

    else:
        # first half revert, second half apply
        # element after switch is ignored
        not_mono_inc = lambda lst: not mono_inc(lst)
        first_half = _takewhile(not_mono_inc, update_path)
        second_half = update_path[len(first_half) + 1 :]  # ignore first element

        for step in first_half:
            access_feed, minv = access_dict[step]
            update_payload = get_payload(access_feed, step - minv + 3)
            changes, _ = bytes_to_changes(update_payload)
            content = apply_changes(content, reverse_changes(changes))

        for step in second_half:
            access_feed, minv = access_dict[step]
            update_payload = get_payload(access_feed, step - minv + 3)
            changes, _ = bytes_to_changes(update_payload)
            content = apply_changes(content, changes)

    return content


def _bfs(graph: Dict[int, List[int]], start: int, end: int) -> List[int]:
    """
    Implements breadth first search. Also returns the found path.
    """
    max_v = max([x for x, _ in graph.items()])

    # label start as visited
    visited = [True if i == start else False for i in range(max_v + 1)]
    queue = [[start]]

    while queue:
        path = queue.pop(0)
        current = path[-1]

        # check if path was found
        if current == end:
            return path

        # explore neighbors
        for n in graph[current]:
            if not visited[n]:
                visited[n] = True
                queue.append(path + [n])

    # should never get here
    return []


def _takewhile(predicate: Callable[[List[int]], bool], lst: List[int]) -> List[int]:
    """
    Own implementation of takewhile (functional programming).
    Removes items from a given list until the given predicate is no longer True.
    Returns the removed items in a new list.
    The input list is not changed.
    """
    final_lst = []

    for i in range(len(lst)):
        if not predicate(lst[i:]):
            break
        final_lst.append(lst[i])

    return final_lst


def changes_to_bytes(changes: List[List], dependency: int) -> bytearray:
    """
    Encodes list of changes and dependency as bytes.
    Dependency is encoded as VarInt.
    The length of each change is also encoded as a VarInt.
    The string index is also encoded as a VarInt.
    The operation is encoded as a single byte insert -> b"I", delete -> b"D"
    The content is encoded as a byte string.
    """
    b = dependency.to_bytes(4, "big")
    for change in changes:
        idx = change[0]
        op = change[1]
        content = change[2]
        b_change = to_var_int(idx) + op.encode() + content.encode()
        b += to_var_int(len(b_change)) + b_change
    return bytearray(b)


def bytes_to_changes(changes: bytearray) -> Tuple[List[List], int]:
    """
    Decodes bytes to changes. Returns a tuple containing:
    (List of changes, update dependency)
    A single change is formatted as follows:
    [string_index, operation(I/D), inserted/deleted string]
    """
    # get dependency
    dependency = int.from_bytes(changes[:4], "big")

    # get changes, iterate over remaining bytes
    curr_i = 4
    operations = []
    len_changes = len(changes)

    while curr_i < len_changes:
        size, num_b = from_var_int(changes[curr_i:])
        curr_i += num_b
        idx, num_b2 = from_var_int(changes[curr_i:])
        curr_i += num_b2
        operation = chr(changes[curr_i])
        curr_i += 1

        str_len = size - num_b2 - 1
        if str_len == 0:
            string = ""
        else:
            string = (changes[curr_i : curr_i + str_len]).decode()

        curr_i += str_len
        operations.append([idx, operation, string])

    return operations, dependency


def reverse_changes(changes: List[List]) -> List[List]:
    """
    Reverses the effects of the given list of changes.
    Used for reverting updates.
    """
    dels = [c for c in changes if c[1] == "D"]
    ins = [c for c in changes if c[1] == "I"]

    # swap
    dels = [[c[0], "I", c[2]] for c in dels]
    ins = [[c[0], "D", c[2]] for c in ins]

    # keep order: delete first, then insert (names were swapped before)
    return ins + dels


def extract_version_graph(
    feed: struct[FEED],
) -> Tuple[Dict[int, List[int]], Dict[int, struct[FEED]]]:
    """
    Computes the version tree of a given file update feed.
    A branch is created by an update dependency.
    """
    # get max version
    # access dict provides feed instance and its base version for a given version number of a file
    # needed, since updates can be located across multiple feeds (through emergency updates)
    access_dict = {}
    max_version = -1
    current_feed = feed

    while True:
        fn_v_tuple = get_upd(current_feed)
        if fn_v_tuple is None:
            break
        _, base_version = fn_v_tuple
        maxv = base_version + length(current_feed) - 3  # account for ICH, UPD and MKC

        max_version = max(maxv, max_version)

        # add feed to access dict
        for i in range(base_version, maxv + 1):
            access_dict[i] = (current_feed, base_version)

        # advance to next feed
        # parent_fid = get_parent(current_feed)
        # if parent_fid is None:
        # break

        # above code works but: pycom maximum recursion depth
        if feed.anchor_seq != 0 or feed.front_seq < 1:
            break

        # get parent feed ID
        try:
            wire = bytearray(48)
            f = open("_feeds/" + hexlify(current_feed.fid).decode() + ".log", "rb")
            wire[:] = f.read(48)
            f.close()
        except Exception:
            # no ISCHILD packet found
            break

        if wire[15:16] != ISCHILD.to_bytes(1, "big"):
            break
        parent_fid = wire[16:48]

        current_feed = get_feed(parent_fid)
        assert current_feed is not None, "failed to get parent"

    # construct version graph
    graph = {}
    for i in range(1, max_version + 1):
        # get individual updates
        if i not in access_dict:
            continue  # missing dependency

        # assuming that update feeds only contain update blobs after initial 3 entries
        # get dependency of update
        current_feed, base_version = access_dict[i]
        dep_on = get_dependency(current_feed, i - base_version + 3)
        if dep_on is None:
            # non CHAIN20 packet type
            continue

        # add edges to graph (both directions)
        if i in graph:
            graph[i] = graph[i] + [dep_on]
        else:
            graph[i] = [dep_on]

        if dep_on in graph:
            graph[dep_on] = graph[dep_on] + [i]
        else:
            graph[dep_on] = [i]

    return graph, access_dict


def string_version_graph(feed: struct[FEED], applied: Optional[int] = None) -> str:
    """
    Returns a string representation of the current update dependency graph.
    The currently applied update is highlighted (dotted box).
    """
    graph, _ = extract_version_graph(feed)

    if graph == {}:
        return ""  # nothing appended to update graph yet

    max_v = max([x for x, _ in graph.items()])
    visited = [True] + [False for _ in range(max_v)]  # mark version 0 as visited
    queue = [[0]]  # deque would be better, limited functionality in micropython
    paths = []
    final_str = ""

    while queue:
        path = queue.pop(0)
        current = path[-1]

        if all([visited[x] for x in graph[current]]):
            paths.append(path)

        for n in graph[current]:
            if not visited[n]:
                visited[n] = True
                queue.append(path + [n])

    nxt = lambda x, lst: lst[lst.index(x) + 1]  # helper lambda
    already_printed = []
    for path in paths:
        string = ""
        top = ""
        bottom = ""
        for step in path:
            if step in already_printed and nxt(step, path) not in already_printed:
                string += "  '----> "
                top += "  |      "
                bottom += " " * 9
            elif step in already_printed:
                string += " " * 9
                top += " " * 9
                bottom += " " * 9
            else:
                already_printed.append(step)
                if applied == step:
                    string += ": {} : -> ".format(step)
                    top += ".....    "
                    bottom += ".....    "
                else:
                    string += "| {} | -> ".format(step)
                    top += "+---+    "
                    bottom += "+---+    "

        final_str += "\n".join([top, string, bottom, ""])
    return final_str
