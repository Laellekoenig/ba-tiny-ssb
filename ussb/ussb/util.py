from os import stat, mkdir
from sys import implementation, platform


# helps with debugging in vim
if implementation.name != "micropython":
    from typing import List, Optional, Tuple


# detect if the code is running on a pycom device
PYCOM = False
if platform in ("FiPy", "LoPy4"):
    PYCOM = True
    from os import listdir as oslistdir
else:
    # listdir does not exist in regular micropython
    from uos import ilistdir


def listdir(path: Optional[str] = None) -> List[str]:
    """
    Returns a list of all files in the given directory (including subdirectories).
    Selects the current path is the input path is None.
    Works on micropython and pycom devices.
    """
    if PYCOM:
        if path is None:
            return oslistdir()
        else:
            return oslistdir(path)
    else:
        if path is None:
            return [name for name, _, _ in list(ilistdir())]
        else:
            return [name for name, _, _ in list(ilistdir(path))]


def walk() -> List[str]:
    """
    Returns a list of all files contained in the current directory and
    every subdirectory. Ignores hidden files (.file_name).
    """
    final = []
    files = listdir()
    while files:
        fn = files.pop(0)
        if fn.startswith(".") or "/." in fn:
            continue

        # check if the file is a directory
        f_stat = stat(fn)[0]
        if (f_stat == 0x81A4 and not PYCOM) or (f_stat == 0x8000 and PYCOM):
            final.append(fn)
        else:
            # search through subdirectory
            files += ["{}/{}".format(fn, x) for x in listdir(fn)]

    return final


def create_dirs_and_file(path: str) -> None:
    """
    Creates an empty file for the given path.
    Also creates directories if they do not exist.
    If the file already exists, it is overwritten.
    """
    # cut file name
    if path.startswith("/"):
        path = path[1:]
    if path.endswith("/"):
        path = path[:-1]

    # separate directories from file name
    split = path.split("/")
    dirs = split[:-1]
    del split

    # create directories if needed
    current_path = None
    for d in dirs:
        if d not in listdir(current_path):
            new_dir = d if current_path is None else "".join([current_path, "/", d])
            mkdir(new_dir)
            del new_dir
        current_path = d if current_path is None else "".join([current_path, "/", d])

    # create empty file
    f = open(path, "wb")
    f.write(b"")
    f.close()


def to_var_int(i: int) -> bytearray:
    """
    Encodes the given positive integer as a VarInt.
    """
    assert i >= 0, "var int must be positive"
    if i <= 252:
        return bytearray([i])
    if i <= 0xFFFF:
        arr = bytearray(3)
        arr[0] = 0xFD
        arr[1:] = i.to_bytes(2, "little")
        return arr
    if i <= 0xFFFFFFFF:
        arr = bytearray(5)
        arr[0] = 0xFE
        arr[1:] = i.to_bytes(4, "little")
        return arr
    arr = bytearray(9)
    arr[0] = 0xFF
    arr[1:] = i.to_bytes(8, "little")
    return arr


def from_var_int(b: bytearray) -> Tuple[int, int]:
    """
    Decodes the VarInt at the beginning of the given bytearray.
    Returns a tuple containing: (decoded VarInt, number of bytes occupied by VarInt).
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
