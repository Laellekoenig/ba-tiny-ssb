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
    from_var_int,
    to_var_int,
)
from .util import listdir, walk, create_dirs_and_file
from json import dumps, loads
from sys import implementation
from ubinascii import hexlify, unhexlify
from uctypes import struct


# helps with debugging in vim
if implementation.name != "micropython":
    # from typing import List
    from typing import List, Tuple, Dict, Callable, Optional


class VersionManager:

    __slots__ = (
        "vc_dict",
        "apply_queue",
        "apply_dict",
        "update_fid",
        "vc_fid",
        "may_update",
        "feed_manager",
    )

    def __init__(self, feed_manager: FeedManager):
        self.feed_manager = feed_manager
        self.vc_dict = {}
        self.apply_queue = {}
        self.apply_dict = {}
        self.update_fid = None
        self.vc_fid = None
        self._load_config()
        if (
            self.update_fid is not None
            and bytes(self.update_fid) in self.feed_manager.keys
        ):
            self.may_update = True
        else:
            self.may_update = False
        self._register_callbacks()

    def __del__(self) -> None:
        self._save_config()

    def _save_config(self) -> None:
        assert self.update_fid is not None
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
        }
        f = open("update_cfg.json", "w")
        f.write(dumps(cfg))
        f.close()

    def _load_config(self) -> None:
        fn = "update_cfg.json"
        if fn not in listdir():
            self.vc_dict = {}
            self.apply_queue = {}
            self.apply_dict = {}
            return

        f = open(fn)
        cfg = loads(f.read())
        f.close()
        del fn

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

        children = get_children(get_feed(self.update_fid))
        if len(children) > 1:
            vc_fid = children[0]
            assert type(vc_fid) is bytearray
            self.vc_fid = vc_fid

    def is_configured(self) -> bool:
        return self.update_fid is not None

    def set_update_feed(self, update_fid: bytearray) -> None:
        self.update_fid = update_fid

        feed = get_feed(update_fid)
        children = get_children(feed)
        if len(children) >= 1:
            vc_fid = children[0]
            assert type(vc_fid) is bytearray
            self.vc_fid = vc_fid

        if bytes(update_fid) not in self.feed_manager.keys:
            self.may_update = False
            self._register_callbacks()
            return

        # callback not needed -> manager of update feed
        self.may_update = True

        files = walk()
        for f in files:
            if (
                f not in self.vc_dict
                and not f[0] == "."
                and not f.endswith(".log")
                and not f.endswith(".json")
                and not f.endswith(".head")
            ):
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
        assert self.update_fid is not None, "no update feed set"
        assert self.update_fid == fid, "not called on update feed"

        # FIXME: can be removed?
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
        assert self.vc_fid is not None, "version control feed not found"

        front_type = get_wire(get_feed(self.vc_fid), -1)[15:16]
        if front_type == ISCHILD.to_bytes(1, "big"):
            return  # first packet in version control feed -> ignore

        if front_type == APPLYUP.to_bytes(1, "big"):
            payload = get_payload(get_feed(self.vc_fid), -1)
            fid, seq = payload[:32], payload[32:36]
            self._apply_update(fid, seq)

    def _file_feed_callback(self, fid: bytearray) -> None:
        feed = get_feed(fid)
        assert feed is not None, "failed to get feed"

        if waiting_for_blob(feed) is not None:
            return  # blob not complete

        # handle depending on newly appended packet type
        front_type = get_wire(feed, -1)[15:16]

        if front_type == CHAIN20.to_bytes(1, "big"):
            # new update arrived
            b_fid = bytes(fid)
            if bytes(b_fid) in self.apply_queue:
                # check if waiting to apply update
                seq = self.apply_queue[b_fid]
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
            fn_v_tuple = get_upd(feed)
            assert fn_v_tuple is not None

            file_name, _ = fn_v_tuple

            # create file if it does not exist
            if file_name not in walk():
                print("creating new file")

                # create directories if necessary
                if "/" in file_name:
                    create_dirs_and_file(file_name)
                else:
                    # create empty file
                    f = open(file_name, "wb")
                    f.write(b"")
                    f.close()

    def _emergency_feed_callback(self, fid: bytearray) -> None:
        feed = get_feed(fid)
        assert feed is not None, "failed to get feed"

        if waiting_for_blob(feed) is not None:
            return  # wait for completion of blob

        front_type = get_wire(feed, -1)[15:16]

        if front_type == MKCHILD.to_bytes(1, "big"):
            # new emergency update incoming
            parent_fid = get_parent(feed)
            assert parent_fid is not None, "failed to find parent"

            # remove callback from old feeds
            self.feed_manager.remove_callback(parent_fid, self._file_feed_callback)
            self.feed_manager.remove_callback(feed.fid, self._emergency_feed_callback)

            # add callback to new feeds
            self.feed_manager.register_callback(feed.fid, self._file_feed_callback)
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
            self.vc_dict[file_name] = (fid, emergency_fid)
            self._save_config()

    def _apply_update(self, fid: bytearray, seq: bytearray) -> None:
        assert self.vc_fid is not None

        # convert
        int_seq = int.from_bytes(seq, "big")
        del seq

        file_feed = get_feed(fid)
        if file_feed is None:
            print("waiting for feed")

            b_fid = bytes(fid)
            if b_fid in self.apply_queue and self.apply_queue[b_fid] == int_seq:
                return  # already in queue

            self.apply_queue[b_fid] = int_seq
            self._save_config()
            return

        # assuming that only updates are appended
        num_updates = length(file_feed) - 3  # subtract ICH UPD and MKC entries
        if num_updates <= 0:
            print("waiting for UPD packet")
            self.apply_queue[bytes(fid)] = int_seq
            self._save_config()
            return

        fn_v_tuple = get_upd(file_feed)
        # FIXME: can this lead to an error?
        assert fn_v_tuple is not None
        file_name, version_num = fn_v_tuple
        newest_version = num_updates + version_num

        if newest_version < int_seq:
            print("waiting for update")
            b_fid = bytes(fid)
            if b_fid in self.apply_queue and self.apply_queue[b_fid] == int_seq:
                return

            self.apply_queue[b_fid] = int_seq
            self._save_config()
            return

        if newest_version == int_seq and waiting_for_blob(file_feed):
            print("waiting for blob")
            b_fid = bytes(fid)
            if b_fid in self.apply_queue and self.apply_queue[b_fid] == int_seq:
                return  # already in queue

            self.apply_queue[b_fid] = int_seq
            self._save_config()
            return

        print("applying {}".format(int_seq))
        f = open(file_name)
        content = f.read()
        f.close()

        current_apply = self.apply_dict[file_name]
        if int_seq == current_apply:
            return

        # compute changes from update and apply them to file
        new_content = jump_versions(content, current_apply, int_seq, file_feed)
        del content

        f = open(file_name, "w")
        f.write(new_content)
        f.close()

        # save updated file
        b_fid = bytes(fid)
        if b_fid in self.apply_queue:
            del self.apply_queue[b_fid]

        self.apply_dict[file_name] = int_seq
        self._save_config()

    def update_file(
        self, file_name: str, changes: List[List], dep: int
    ) -> None:  # inner list contains index, I/D, content
        assert self.vc_fid is not None

        if not self.may_update:
            print("may not append new updates")
            return

        if file_name not in self.vc_dict:
            # print("file does not exist")
            return None

        if dep < 0:
            print("invalid dependency")
            return None

        # get feed
        fid, _ = self.vc_dict[file_name]
        feed = get_feed(fid)
        assert feed is not None, "failed to get feed"
        fn_v_tuple = get_upd(feed)
        assert fn_v_tuple is not None
        _, minv = fn_v_tuple
        current_v = length(feed) - 3 + minv

        if dep > current_v:
            print("dependency does not exist yet")
            return None

        # append to feed
        self.feed_manager.append_blob_to_feed(feed, changes_to_bytes(changes, dep))

    def emergency_update_file(
        self, file_name: str, changes: List[List], depends_on: int
    ) -> Optional[int]:
        assert self.vc_fid is not None, "need vc feed to update"

        if not self.may_update:
            print("may not append new updates")
            return

        if file_name not in self.vc_dict:
            return

        old_fid, emgcy_fid = self.vc_dict[file_name]
        old_feed = get_feed(old_fid)
        emgcy_feed = get_feed(emgcy_fid)
        ekey = self.feed_manager.get_key(emgcy_fid)
        assert ekey is not None

        # get newest update number of old feed
        fn_v_tuple = get_upd(old_feed)
        assert fn_v_tuple is not None
        _, minv = fn_v_tuple
        maxv = minv + length(old_feed) - 3
        # remove callback
        self.feed_manager.remove_callback(old_fid, self._file_feed_callback)
        del old_fid, old_feed, fn_v_tuple

        # add upd packet to emergency feed, making it new update feed
        add_upd(emgcy_feed, file_name, ekey, maxv)

        # switch to emergency feed
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
        self.feed_manager.remove_callback(emgcy_fid, self._emergency_feed_callback)
        self.feed_manager.register_callback(emgcy_fid, self._file_feed_callback)
        self.feed_manager.register_callback(nfid, self._emergency_feed_callback)

    def add_apply(self, file_name: str, v_num: int) -> None:
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

        # convert negative indices
        fn_v_tuple = get_upd(feed)
        assert fn_v_tuple is not None
        _, minv = fn_v_tuple
        current_version_num = minv + length(feed) - 3

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

    def create_new_file(self, file_name: str) -> None:
        assert self.update_fid is not None
        print("creating new file: {}".format(file_name))

        if file_name in walk():
            print("file already exists")
            return

        create_dirs_and_file(file_name)

        # create new feed
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
    ins = [c for c in changes if c[1] == "I"]
    dels = [c for c in changes if c[1] == "D"]
    dels.reverse()

    for change in dels:
        idx = change[0]
        string = change[2]

        # delete
        content = content[:idx] + content[idx + len(string):]

    for change in ins:
        idx = change[0]
        string = change[2]

        # insert
        content = content[:idx] + string + content[idx:]

    return content


def jump_versions(content: str, start: int, end: int, feed: struct[FEED]) -> str:
    if start == end:
        return content  # nothing changes

    # get dependency graph
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
    final_lst = []

    for i in range(len(lst)):
        if not predicate(lst[i:]):
            break
        final_lst.append(lst[i])

    return final_lst


def bytes_to_changes(changes: bytearray) -> Tuple[List[List], int]:
    dependency = int.from_bytes(changes[:4], "big")
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
    dels = [c for c in changes if c[1] == "D"]
    ins = [c for c in changes if c[1] == "I"]

    # swap
    dels = [[c[0], "I", c[2]] for c in dels]
    ins = [[c[0], "D", c[2]] for c in ins]


    return ins + dels


def extract_version_graph(
    feed: struct[FEED],
) -> Tuple[Dict[int, List[int]], Dict[int, struct[FEED]]]:
    # get max version
    access_dict = {}
    max_version = -1
    current_feed = feed
    while True:
        fn_v_tuple = get_upd(current_feed)
        if fn_v_tuple is None:
            break
        _, minv = fn_v_tuple
        fn_v_tuple = get_upd(current_feed)
        assert fn_v_tuple is not None
        _, minv = fn_v_tuple
        maxv = minv + length(current_feed) - 3  # account for ICH, UPD and MKC

        max_version = max(maxv, max_version)

        # add feed to access dict
        for i in range(minv, maxv + 1):
            access_dict[i] = (current_feed, minv)

        # advance to next feed
        parent_fid = get_parent(current_feed)
        if parent_fid is None:
            break

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
        current_feed, minv = access_dict[i]
        dep_on = get_dependency(current_feed, i - minv + 3)
        if dep_on is None:
            # non CHAIN20 packet type
            continue

        if i in graph:
            graph[i] = graph[i] + [dep_on]
        else:
            graph[i] = [dep_on]

        if dep_on in graph:
            graph[dep_on] = graph[dep_on] + [i]
        else:
            graph[dep_on] = [i]

    return graph, access_dict


def changes_to_bytes(changes: List[List], dependency: int) -> bytearray:
    b = dependency.to_bytes(4, "big")
    for change in changes:
        idx = change[0]
        op = change[1]
        content = change[2]
        b_change = to_var_int(idx) + op.encode() + content.encode()
        b += to_var_int(len(b_change)) + b_change
    return bytearray(b)


def string_version_graph(feed: struct[FEED], applied: Optional[int] = None) -> str:
    """
    Prints a representation of the current update dependency graph. The currently
    applied update is highlighted.
    """
    graph, _ = extract_version_graph(feed)

    if graph == {}:
        return ""  # nothing appended to update graph yet

    max_v = max([x for x, _ in graph.items()])
    visited = [True] + [False for _ in range(max_v)]  # mark version 0 as visited
    queue = [[0]]  # deque would be better, not available in micropython on pycom
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
