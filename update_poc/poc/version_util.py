import sys
from collections import deque
from tinyssb.feed import Feed
from tinyssb.ssb_util import to_var_int, from_var_int
from typing import Callable, Optional

# non-micropython import
if sys.implementation.name != "micropython":
    # Optional type annotations are ignored in micropython
    from typing import List, Tuple, Dict


def takewhile(predicate: Callable[[List[int]], bool], lst: List[int]) -> List[int]:
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
    required to get from old version to new version.
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
            # TODO: content of deleted line necessary? -> allow reverts?
            changes.append((line_num, "D", old_l))
            new_lines.insert(0, new_l)  # put new line back
            continue

        # old line occurs later in file -> insert new line
        old_lines.insert(0, old_l)  # return to list

        changes.append((line_num, "I", new_l))
        line_num += 1

    # old lines left -> must be deleted
    for line in old_lines:
        changes.append((line_num, "D", line))

    # new line left -> insert at end
    for line in new_lines:
        changes.append((line_num, "I", line))
        line_num += 1

    return changes


def changes_to_bytes(changes: List[Tuple[int, str, str]], dependency: int) -> bytes:
    """
    Encodes a given list of changes into a single bytes string.
    """
    b = dependency.to_bytes(4, "big")
    for change in changes:
        i, op, ln = change  # unpack tuple
        b_change = to_var_int(i) + op.encode() + ln.encode()
        b += to_var_int(len(b_change)) + b_change

    return b

def bytes_to_changes(changes: bytes) -> Tuple[List[Tuple[int, str, str]], int]:
    """
    Takes bytes that are encoded by get_file_changes() and returns
    the operations in a list.
    Every operation is a tuple containing:
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

        if op == "I":
            # insert
            old_lines.insert(line_num, content)

        if op == "D":
            # delete
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
    try:
        msg = "writing file: {}".format(file_name)
        separator = "\"" * len(msg)
        print("\n".join([msg, separator]))
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
    """

    changes = [(a, "I", c) if b == "D" else (a, "D", c) for a, b, c in changes]
    changes.reverse()
    return changes

def jump_versions(start: int, end: int, feed: Feed) -> List[Tuple[int, str, str]]:
    print("{} to {}".format(start, end))
    # extract all versions and dependencies from feed
    if start == end:
        return []

    num_updates = feed.count_chain20()

    if start > num_updates or end > num_updates:
        print("update not available yet")
        return []

    neighbors = {}
    for i in range(1, num_updates + 1):
        # get individual updates
        update = feed.get_chain20(i)
        # extract dependency
        dep_on = int.from_bytes(update[:4], "big")

        if i in neighbors:
            neighbors[i] = neighbors[i] + [dep_on]
        else:
            neighbors[i] = [dep_on]

        if dep_on in neighbors:
            neighbors[dep_on] = neighbors[dep_on] + [i]
        else:
            neighbors[dep_on] = [i]

    # do BFS on graph
    update_path = _dfs(neighbors, start, end)
    print(update_path)

    mono_inc = lambda lst: all(x < y for x, y in zip(lst, lst[1:]))
    mono_dec = lambda lst: all(x > y for x, y in zip(lst, lst[1:]))

    all_changes = []

    if mono_inc(update_path):
        # apply all updates, ignore first
        update_path.pop(0)
        for step in update_path:
            changes, _ = bytes_to_changes(feed.get_chain20(step))
            all_changes += changes

    elif mono_dec(update_path):
        # revert all updates, ignore last
        update_path.pop()
        for step in update_path:
            changes, _ = bytes_to_changes(feed.get_chain20(step))
            all_changes += reverse_changes(changes)

    else:
        # first half revert, second half apply
        # element after switch is ignored
        not_mono_inc = lambda lst: not mono_inc(lst)
        first_half = takewhile(not_mono_inc, update_path)
        second_half = update_path[len(first_half) + 1:]  # ignore first element
        print(first_half)
        print(second_half)

        for step in first_half:
            changes, _ = bytes_to_changes(feed.get_chain20(step))
            all_changes += reverse_changes(changes)

        for step in second_half:
            changes, _ = bytes_to_changes(feed.get_chain20(step))
            all_changes += changes

    return all_changes


def _dfs(graph: Dict[int, List[int]], start: int, end: int) -> List[int]:
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
                queue.append(path + [n])

    # should never get here
    return []
