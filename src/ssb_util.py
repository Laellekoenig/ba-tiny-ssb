import os
import binascii as bin
# uncomment following line for micropython
# import ubinascii as bin


def is_file(file_name: str) -> bool:
    """checks whether file or dir already exists"""
    dir_prefix = None
    if "/" in file_name:
        split = file_name.split("/")
        dir_prefix = "/".join(split[:-1])
        file_name = split[-1]

    return file_name in os.listdir(dir_prefix)


def to_hex(b: bytes) -> str:
    """transforms bytes to hex string representation"""
    return bin.hexlify(b).decode()


def from_hex(s: str) -> bytes:
    """transforms hex string to bytes"""
    return bin.unhexlify(s.encode())


def to_var_int(i: int) -> bytes:
    """transforms an int into a 'Variable Integer' as used in bitcoin
    to indicate the lengths of fields within transactions"""
    assert i >= 0, "var int must be positive"
    if i <= 252:
        return bytes([i])
    if i <= 0xffff:
        return b"\xfd" + i.to_bytes(2, "little")
    if i <= 0xffffffff:
        return b"\xfe" + i.to_bytes(4, "little")
    return b"\xff" + i.to_bytes(8, "little")


def from_var_int(b: bytes) -> (int, int):
    """transforms bytes from 'Variable Integer' format back to int
    returns (number, number of bytes)"""
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
