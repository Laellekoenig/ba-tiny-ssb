import os
import binascii as bin
# uncomment following line for micropython
# import ubinascii as bin


def is_file(file_name: str) -> bool:
    """
    Checks whether the given file name exists.
    Works for directories and files.
    Supports checking for files in subdirectories (e.g. 'example/file.txt').
    Directory names may not end with '/'.
    """
    dir_prefix = None
    if "/" in file_name:
        split = file_name.split("/")
        dir_prefix = "/".join(split[:-1])
        file_name = split[-1]

    return file_name in os.listdir(dir_prefix)


def to_hex(b: bytes) -> str:
    """
    Returns the bytes as a hex string.
    """
    return bin.hexlify(b).decode()


def from_hex(s: str) -> bytes:
    """Returns the hex string as bytes."""
    return bin.unhexlify(s.encode())


def to_var_int(i: int) -> bytes:
    """
    Transforms an int into a 'Variable Integer' as used in Bitcoin.
    Depending on the size of the int, either 1B, 3B, 5B or 9B are returned.
    The provided int must be larger or equal to 0.
    Used to indicate the length of a blob.
    """
    assert i >= 0, "var int must be positive"
    if i <= 252:
        return bytes([i])
    if i <= 0xffff:
        return b"\xfd" + i.to_bytes(2, "little")
    if i <= 0xffffffff:
        return b"\xfe" + i.to_bytes(4, "little")
    return b"\xff" + i.to_bytes(8, "little")


def from_var_int(b: bytes) -> (int, int):
    """
    Transforms a 'Variable Integer' back to its int representation.
    Returns the converted int and the number of bytes used by the VarInt
    representation.
    """
    assert len(b) >= 1
    head = b[0]
    if head <= 252:
        return (head, 1)
    assert len(b) >= 3
    if head == 0xfd:
        return (int.from_bytes(b[1:3], "little"), 3)
    assert len(b) >= 5
    if head == 0xfe:
        return (int.from_bytes(b[1:5], "little"), 5)
    assert len(b) >= 9
    return (int.from_bytes(b[1:9], "little"), 9)
