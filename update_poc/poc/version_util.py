from os import execl
import sys
from typing import Optional
from tinyssb.ssb_util import to_var_int, from_var_int

# non-micropython import
if sys.implementation.name != "micropython":
    # Optional type annotations are ignored in micropython
    from typing import List, Tuple


def get_file_changes(old_version: str, new_version: str) -> bytes:
    """
    Takes two strings as input, the first being the old file and the second one
    being the updated version. Determines the insert and delete operations
    required to get from old version to new version. These operations are
    encoded as bytes so they can be appended to an update feed.
    """
    changes = b""
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
            change = to_var_int(line_num) + "D".encode() + old_l.encode()
            changes += to_var_int(len(change)) + change
            new_lines.insert(0, new_l)  # put new line back
            continue

        # old line occurs later in file -> insert new line
        old_lines.insert(0, old_l)  # return to list

        change = to_var_int(line_num) + "I".encode() + new_l.encode()
        changes += to_var_int(len(change)) + change
        line_num += 1

    # old lines left -> must be deleted
    for line in old_lines:
        change = to_var_int(line_num) + "D".encode() + line.encode()
        changes += to_var_int(len(change)) + change

    # new line left -> insert at end
    for line in new_lines:
        change = to_var_int(line_num) + "I".encode() + line.encode()
        changes += to_var_int(len(change)) + change
        line_num += 1

    return changes


def bytes_to_changes(changes: bytes) -> List[Tuple[int, str, str]]:
    """
    Takes bytes that are encoded by get_file_changes() and returns
    the operations in a list.
    Every operation is a tuple containing:
    - line_number
    - operation: I -> insert, D -> delete
    - line content
    """
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

    return operations


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
        f = open(path + "/" + file_name, "w")
        f.write(content)
        f.close()
        return True
    except:
        print("failed to write to file {}".format(file_name))
        return False
