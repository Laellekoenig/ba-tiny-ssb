import sys
from .feed import Feed
from .feed_manager import FeedManager
from .ssb_util import to_var_int, from_var_int
from collections import deque
from typing import Callable, Optional


# non-micropython import
if sys.implementation.name != "micropython":
    # Optional type annotations are ignored in micropython
    from typing import List, Tuple, Dict


def _takewhile(predicate: Callable[[List[int]], bool], lst: List[int]) -> List[int]:
    """
    Takes (does not remove) items from the given list until the given predicate is
    no longer satisfied. Returns these elements in a new list.
    """
    final_lst = []

    for i in range(len(lst)):
        if not predicate(lst[i:]):
            break
        final_lst.append(lst[i])

    return final_lst


def get_changes(old_version: str, new_version: str) -> List[Tuple[int, str, str]]:
    """
    Takes two strings as input, the first being the old file and the second one
    being the updated version. Determines the insert and delete operations
    required to get from the old version to new version.
    These changes are returned as tuples consisting of:
    - line number
    - operation: D -> delete, I -> insert
    - content of line
    """
    changes = []
    old_lines = old_version.split("\n")
    new_lines = new_version.split("\n")

    line_num = 1
    while len(old_lines) > 0 and len(new_lines) > 0:
        old_l = old_lines.pop(0)
        new_l = new_lines.pop(0)

        # lines are the same -> no changes
        if old_l == new_l:
            line_num += 1
            continue

        # lines are different
        if old_l not in new_lines:
            # line was deleted
            changes.append((line_num, "D", old_l))
            new_lines.insert(0, new_l)  # retry new line in next iteration
            continue

        # old line occurs later in file -> insert new line
        old_lines.insert(0, old_l)  # retry new line in next iteration

        changes.append((line_num, "I", new_l))
        line_num += 1

    # old line(s) left -> must be deleted
    for line in old_lines:
        changes.append((line_num, "D", line))

    # new line(s) left -> insert at end
    for line in new_lines:
        changes.append((line_num, "I", line))
        line_num += 1

    return changes


def changes_to_bytes(changes: List[Tuple[int, str, str]], dependency: int) -> bytes:
    """
    Encodes a given list of changes into bytes. These can be appended to a feed.
    """
    b = dependency.to_bytes(4, "big")
    for change in changes:
        i, op, ln = change  # unpack triple
        b_change = to_var_int(i) + op.encode() + ln.encode()
        b += to_var_int(len(b_change)) + b_change

    return b


def bytes_to_changes(changes: bytes) -> Tuple[List[Tuple[int, str, str]], int]:
    """
    Takes bytes that are encoded by get_file_changes() and returns the operations in a list.
    Every operation is a triple containing:
    - line_number
    - operation: I -> insert, D -> delete
    - line content
    """
    dependency = int.from_bytes(changes[:4], "big")
    changes = changes[4:]
    operations = []
    while len(changes) > 0:
        size, size_b = from_var_int(changes)
        changes = changes[size_b:]
        change = changes[:size]
        changes = changes[size:]  # cut off

        # decode change
        line_num, num_b = from_var_int(change)
        operation = chr(change[num_b])
        string = (change[num_b + 1 :]).decode()

        operations.append((line_num, operation, string))

    return operations, dependency


def apply_changes(content: str, changes: List[Tuple[int, str, str]]) -> str:
    """
    Applies every operation in the given list to the given string.
    The definition of an operation can be found in bytes_to_changes().
    """
    old_lines = content.split("\n")

    for change in changes:
        line_num, op, content = change
        line_num -= 1  # adjust for 0 index

        if op == "I":  # insert
            old_lines.insert(line_num, content)

        if op == "D":  # delete
            del old_lines[line_num]

    return "\n".join(old_lines)


def read_file(path: str, file_name: str) -> Optional[str]:
    """
    Reads the content of a given path + file name and returns it as a string.
    If the file is not found or cannot be read, None is returned.
    """
    content = None
    try:
        f = open(path + "/" + file_name, "r")
        content = f.read()
        f.close()
    except Exception:
        print("failed to read file {}".format(file_name))

    return content


def write_file(path: str, file_name: str, content: str) -> bool:
    """
    Overwrites the content of a given file with the given content.
    Returns True on success.
    """
    msg = "writing to file: {}".format(file_name)
    separator = '"' * len(msg)
    print("\n".join([msg, separator]))

    try:
        f = open(path + "/" + file_name, "w")
        f.write(content)
        f.close()
        return True
    except:
        print("failed to write to file {}".format(file_name))
        return False


def reverse_changes(changes: List[Tuple[int, str, str]]) -> List[Tuple[int, str, str]]:
    """
    Reverses the effects of the given list of changes.
    These are returned as a new list of changes.
    """
    changes = [(a, "I", c) if b == "D" else (a, "D", c) for a, b, c in changes]
    changes.reverse()
    return changes


def string_version_graph(
    feed: Feed, feed_manager: FeedManager, applied: Optional[int] = None
) -> str:
    """
    Prints a representation of the current update dependency graph. The currently
    applied update is highlighted.
    """
    graph, _ = extract_version_graph(feed, feed_manager)

    if graph == {}:
        return ""  # nothing appended to update graph yet

    max_v = max([x for x, _ in graph.items()])
    visited = [True] + [False for _ in range(max_v)]  # mark version 0 as visited
    queue = deque()
    queue.append([0])  # start from version 0
    paths = []
    final_str = ""

    while queue:
        path = queue.popleft()
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


def extract_version_graph(
    feed: Feed, feed_manager: FeedManager
) -> Tuple[Dict[int, List[int]], Dict[int, Feed]]:
    """
    Creates a graph, representing all update dependencies that are present in the
    given feed. The graph is represented as dictionary, where the key is the version
    number of a node and the value is a list of neighboring version numbers.
    Returns a tuple containing the graph dictionary and a dictionary containing
    access information for each node (since entries can be part of parent feed).
    """
    # get max version
    access_dict = {}
    max_version = -1
    current_feed = feed
    while True:
        minv = current_feed.get_upd_version()
        if minv is None:
            break

        maxv = current_feed.get_current_version_num()
        if maxv is None:
            break

        max_version = max(maxv, max_version)

        # add feed to access dict
        for i in range(minv, maxv + 1):
            access_dict[i] = current_feed

        # advance to next feed
        parent_fid = current_feed.get_parent()
        if parent_fid is None:
            break

        current_feed = feed_manager.get_feed(parent_fid)
        assert current_feed is not None, "failed to get parent"

    # construct version graph
    graph = {}
    for i in range(1, max_version + 1):
        # get individual updates
        if i not in access_dict:
            continue  # missing dependency

        dep_on = access_dict[i].get_dependency(i)
        if dep_on is None:
            print("WARNING dependency is None in extract tree")  # for debugging

        if i in graph:
            graph[i] = graph[i] + [dep_on]
        else:
            graph[i] = [dep_on]

        if dep_on in graph:
            graph[dep_on] = graph[dep_on] + [i]
        else:
            graph[dep_on] = [i]

    return graph, access_dict


def jump_versions(
    start: int, end: int, feed: Feed, feed_manager: FeedManager
) -> List[Tuple[int, str, str]]:
    """
    Computes the changes needed to get from starting version to ending version.
    These changes are returned as a list of triples.
    """
    if start == end:
        return []  # nothing changes

    # get dependency graph
    graph, access_dict = extract_version_graph(feed, feed_manager)
    max_version = max([x for x, _ in access_dict.items()])

    if start > max_version or end > max_version:
        print("update not available yet")
        return []

    # do BFS on graph
    update_path = _bfs(graph, start, end)

    # three different types of paths:
    # [1, 2, 3, 4] -> only apply: 1 already applied, apply 2, 3, 4
    # [4, 3, 2, 1] -> only revert: revert 4, 3, 2 to get to version 1
    # [2, 1, 3, 4] -> revert first, then apply: revert 2, apply 3, 4
    # [1, 2, 1, 3] -> does not exist (not shortest path)
    mono_inc = lambda lst: all(x < y for x, y in zip(lst, lst[1:]))
    mono_dec = lambda lst: all(x > y for x, y in zip(lst, lst[1:]))

    all_changes = []

    if mono_inc(update_path):
        # apply all updates, ignore first
        update_path.pop(0)
        for step in update_path:
            access_feed = access_dict[step]
            update_blob = access_feed.get_update_blob(step)
            assert update_blob is not None, "failed to get update blob"
            changes, _ = bytes_to_changes(update_blob)
            all_changes += changes

    elif mono_dec(update_path):
        # revert all updates, ignore last
        update_path.pop()
        for step in update_path:
            access_feed = access_dict[step]
            update_blob = access_feed.get_update_blob(step)
            assert update_blob is not None, "failed to get update blob"
            changes, _ = bytes_to_changes(update_blob)
            all_changes += reverse_changes(changes)

    else:
        # first half revert, second half apply
        # element after switch is ignored
        not_mono_inc = lambda lst: not mono_inc(lst)
        first_half = _takewhile(not_mono_inc, update_path)
        second_half = update_path[len(first_half) + 1 :]  # ignore first element

        for step in first_half:
            access_feed = access_dict[step]
            update_blob = access_feed.get_update_blob(step)
            assert update_blob is not None, "failed to get update blob"
            changes, _ = bytes_to_changes(update_blob)
            all_changes += reverse_changes(changes)

        for step in second_half:
            access_feed = access_dict[step]
            update_blob = access_feed.get_update_blob(step)
            assert update_blob is not None, "failed to get update blob"
            changes, _ = bytes_to_changes(update_blob)
            all_changes += changes

    return all_changes


def _bfs(graph: Dict[int, List[int]], start: int, end: int) -> List[int]:
    """
    Performs breadth-first search on a given graph from starting to ending node.
    Returns the shortest path as a list of version numbers.
    """
    max_v = max([x for x, _ in graph.items()])

    # label start as visited
    visited = [True if i == start else False for i in range(max_v + 1)]
    queue = deque()
    queue.append([start])

    while queue:
        path = queue.popleft()
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
