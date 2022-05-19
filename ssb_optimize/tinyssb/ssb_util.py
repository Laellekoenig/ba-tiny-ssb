import pure25519
import sys


if sys.implementation.name == "micropython":
    # micropython
    import ubinascii as bin
else:
    # regular python
    import binascii as bin
    from typing import Tuple, List, Optional


def read_file(file_name: str) -> Optional[str]:
    """
    Reads the content of a given path + file name and returns it as a string.
    If the file is not found or cannot be read, None is returned.
    """
    file_name = file_name[1:] if file_name.startswith("/") else file_name

    content = None
    try:
        f = open(file_name, "r")
        content = f.read()
        f.close()
    except Exception:
        print("failed to read file {}".format(file_name))

    return content


def write_file(file_name: str, content: str) -> bool:
    """
    Overwrites the content of a given file with the given content.
    Returns True on success.
    """
    msg = "writing to file: {}".format(file_name)
    separator = '"' * len(msg)
    print("\n".join([msg, separator]))

    try:
        f = open(file_name, "w")
        f.write(content)
        f.close()
        return True
    except:
        print("failed to write to file {}".format(file_name))
        return False


def is_file(file_name: str) -> bool:
    """
    Checks whether the given file name exists. Works for directories and files.
    Supports checking for files in subdirectories (e.g. 'example/file.txt').
    Directory names may not end with '/'.
    """
    dir_prefix = None
    if "/" in file_name:
        split = file_name.split("/")
        dir_prefix = "/".join(split[:-1])
        file_name = split[-1]

    if dir_prefix is None:
        return file_name in os.listdir()
    else:
        return file_name in os.listdir(dir_prefix)


def is_dir(path: str) -> bool:
    """
    Returns True if the given path is a directory
    and False if the given path is a file.
    """
    try:
        f = open(path, "r")
        f.close()
        return False
    except Exception:
        return True


def dir_exists(path: str) -> bool:
    """
    Returns True if there exists a directory with the given path
    """
    path = path[1:] if path.startswith("/") else path
    path = path[:-1] if path.endswith("/") else path
    dir_path = None

    if "/" in path:
        split = path.split("/")
        dir_path = "/".join(split[:-1])
        path = split[-1]

    return path in os.listdir(dir_path)


def walk(path: Optional[str] = None) -> List[str]:
    """
    Own (micropython compatible) implementation of os.walk
    Returns a list of all files contained within the given directory,
    including all subdirectories.
    """
    if path:
        path = path[1:] if path.startswith("/") else path
        path = path[:-1] if path.endswith("/") else path

    is_file = lambda x: not is_dir(x)  # helper lambda
    listdir = os.listdir(path)
    listdir = [fn if path is None else path + "/" + fn for fn in listdir]

    dirs = list(filter(is_dir, listdir))
    files = list(filter(is_file, listdir))

    while dirs:
        current_dir = dirs.pop()
        listdir = [current_dir + "/" + p for p in os.listdir(current_dir)]

        dirs += list(filter(is_dir, listdir))
        files += list(filter(is_file, listdir))

    # remove path again
    if path is not None:
        files = [fn[len(path) + 1 :] for fn in files]  # +1 for the added parenthesis

    return files


def mk_dir(path: str) -> None:
    """
    Creates all of the directories, contained in the given path.
    """
    path = path[1:] if path.startswith("/") else path

    dirs = path.split("/")
    current_dir = ""
    for d in dirs:
        current_dir += d + "/"
        if dir_exists(current_dir):
            continue
        os.mkdir(current_dir)


def to_hex(b: bytes) -> str:
    """
    Returns the given bytes as a hex string.
    """
    return bin.hexlify(b).decode()


def from_hex(s: str) -> bytes:
    """Returns the given hex string as bytes."""
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
    if i <= 0xFFFF:
        return b"\xfd" + i.to_bytes(2, "little")
    if i <= 0xFFFFFFFF:
        return b"\xfe" + i.to_bytes(4, "little")
    return b"\xff" + i.to_bytes(8, "little")


def from_var_int(b: bytes) -> Tuple[int, int]:
    """
    Transforms a 'Variable Integer' back to its int representation.
    Returns the converted int and the number of bytes used by the VarInt representation.
    """
    assert len(b) >= 1
    head = b[0]
    if head <= 252:
        return (head, 1)
    assert len(b) >= 3
    if head == 0xFD:
        return (int.from_bytes(b[1:3], "little"), 3)
    assert len(b) >= 5
    if head == 0xFE:
        return (int.from_bytes(b[1:5], "little"), 5)
    assert len(b) >= 9
    return int.from_bytes(b[1:9], "little"), 9


def create_keypair() -> Tuple[bytes, bytes]:
    """
    Creates a key pair for signing with elliptic curve.
    Both keys are 32B and are returned as a tuple (signing key first, verification key second).
    """
    key, _ = pure25519.create_keypair()
    skey = key.sk_s[:32]
    vkey = key.vk_s
    return skey, vkey
