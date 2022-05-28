from os import stat, mkdir
from sys import implementation, platform


PYCOM = False
if platform in ("FiPy", "LoPy"):
    PYCOM = True
    from os import listdir as oslistdir
else:
    from uos import ilistdir


# helps with debugging in vim
if implementation.name != "micropython":
    # from typing import List
    from typing import List, Optional


def listdir(path: Optional[str] = None) -> List[str]:
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
    final = []
    files = listdir()
    while files:
        fn = files.pop(0)
        if fn.startswith(".") or "/." in fn:
            continue

        f_stat = stat(fn)[0]
        if (f_stat == 0x81A4 and not PYCOM) or (f_stat == 0x8000 and PYCOM):
            final.append(fn)
        else:
            files += ["{}/{}".format(fn, x) for x in listdir(fn)]

    return final


def create_dirs_and_file(path: str) -> None:
    if path.startswith("/"):
        path = path[1:]
    if path.endswith("/"):
        path = path[:-1]

    split = path.split("/")
    dirs = split[:-1]
    del split

    current_path = None
    for d in dirs:
        if d not in listdir(current_path):
            new_dir = d if current_path is None else "".join([current_path, "/", d])
            mkdir(new_dir)
            del new_dir
        current_path = d if current_path is None else "".join([current_path, "/", d])

    f = open(path, "wb")
    f.write(b"")
    f.close()
