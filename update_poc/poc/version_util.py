from tinyssb.ssb_util import to_var_int, from_var_int
import sys


# non-micropython import
if sys.implementation.name != "micropython":
    # Optional type annotations are ignored in micropython
    from typing import List, Tuple


def get_file_delta(path: str, file_name: str, new_version: str) -> bytes:
    # get "old" content
    old_file = open(path + "/" + file_name, "r")
    old_version = old_file.read()
    old_file.close()

    # compare with new version
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
            change = to_var_int(line_num) + "D".encode() + old_l.encode()
            changes += to_var_int(len(change)) + change
            new_lines.insert(0, new_l)  # put new line back
            continue

        # old line occurs later in file -> insert new line
        old_lines.insert(0, old_l)  # return to lst

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


def delta_from_bytes(changes: bytes) -> List[Tuple[int, str, str]]:
    delta = []
    while len(changes) > 0:
        size, size_b = from_var_int(changes)
        changes = changes[size_b:]
        change = changes[:size]
        changes = changes[size:]  # cut off

        # decode change
        line_num, num_b = from_var_int(change)
        operation = chr(change[num_b])
        string = (change[num_b + 1:]).decode()

        delta.append((line_num, operation, string))

    return delta


def apply_changes(path: str, file_name: str,
                  changes: List[Tuple[int, str, str]]) -> None:

    # read old file
    f = open(path + "/" + file_name, "r")
    old_file = f.read()
    f.close()

    # apply changes to string
    old_lines = old_file.split("\n")

    for change in changes:
        line_num, op, content = change
        line_num -= 1  # adjust for 0 index
        
        if op == "I":
            # insert
            old_lines.insert(line_num, content)

        if op == "D":
            # delete
            del old_lines[line_num]

    # save back to file
    new_file = "\n".join(old_lines)
    f = open(path + "/" + file_name, "w")
    f.write(new_file)
    f.close()
