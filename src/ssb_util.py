import os
import binascii as bin
# uncomment following line for micropython
# import ubinascii as bin


def is_file(file_name: str) -> bool:
    """checks whether file or dir already exists"""
    return file_name in os.listdir()


def to_hex(b: bytes) -> str:
    """transforms bytes to hex string representation"""
    return bin.hexlify(b).decode()


def from_hex(s: str) -> bytes:
    """transforms hex string to bytes"""
    return bin.unhexlify(s.encode())
