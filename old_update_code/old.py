def reverse_changes(changes: List[Tuple[int, str, str]]) -> List[Tuple[int, str, str]]:
    changes = [(a, "I", c) if b == "D" else (a, "D", c) for a, b, c in changes]
    changes.reverse()
    return changes


def get_changes(old_version: str, new_version: str) -> List[Tuple[int, str, str]]:
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

        if new_l not in old_lines:
            changes.append((line_num, "I", new_l))
            old_lines.insert(0, old_l)
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


def changes_to_bytes(changes: List[Tuple[int, str, str]], dependency: int) -> bytearray:
    b = dependency.to_bytes(4, "big")
    for change in changes:
        i, op, ln = change  # unpack triple
        # if ln == "":
        # b_change = to_var_int(i) + op.encode() + bytes(1)  # encode empty line as null
        # else:
        b_change = to_var_int(i) + op.encode() + ln.encode()
        b += to_var_int(len(b_change)) + b_change
    return bytearray(b)


def bytes_to_changes(changes: bytearray) -> Tuple[List[Tuple[int, str, str]], int]:
    # assert 1 == 0
    dependency = int.from_bytes(changes[:4], "big")
    curr_i = 4
    operations = []
    len_changes = len(changes)
    while curr_i < len_changes:
        size, num_b = from_var_int(changes[curr_i:])
        curr_i += num_b
        line_num, num_b2 = from_var_int(changes[curr_i:])
        curr_i += num_b2
        operation = chr(changes[curr_i])
        curr_i += 1

        str_len = size - num_b2 - 1
        if str_len == 0:
            string = ""
        else:
            string = (changes[curr_i : curr_i + str_len]).decode()

        curr_i += str_len
        operations.append((line_num, operation, string))

    return operations, dependency


def apply_changes(content: str, changes: List[Tuple[int, str, str]]) -> str:
    old_lines = content.split("\n")

    for change in changes:
        line_num, op, content = change
        line_num -= 1  # adjust for 0 index

        if op == "I":  # insert
            old_lines.insert(line_num, content)

        if op == "D":  # delete
            del old_lines[line_num]

    return "\n".join(old_lines)

def emergency_update_file(
    self, file_name: str, update: str, depends_on: int
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
    self.update_file(file_name, update, depends_on)
    # and apply
    self.add_apply(file_name, maxv + 1)

    # update callbacks
    self.feed_manager.remove_callback(emgcy_fid, self._emergency_feed_callback)
    self.feed_manager.register_callback(emgcy_fid, self._file_feed_callback)
    self.feed_manager.register_callback(nfid, self._emergency_feed_callback)
