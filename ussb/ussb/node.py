from .feed import listdir
from .feed_manager import FeedManager
from json import dumps, loads
from sys import implementation
from ubinascii import hexlify, unhexlify


# helps with debugging in vim
if implementation.name != "micropython":
    pass
    # from typing import Union


class Node:

    __slots__ = (
        "feed_manager",
        "master_fid",
        "queue",
    )

    def __init__(self, enable_http: bool = False) -> None:
        self.feed_manager = FeedManager()
        self.master_fid = None
        self._load_config()

        self.queue = []

        if enable_http and self.master_fid:
            # TODO: webserver
            pass

    def __del__(self) -> None:
        self._save_config()

    def _save_config(self) -> None:
        if self.master_fid is None:
            return

        cfg = {"master_fid": hexlify(bytes(self.master_fid)).decode()}
        f = open("node_cfg.json", "w")
        f.write(dumps(cfg))
        f.close()

    def _load_config(self) -> None:
        file_name = "node_cfg.json"
        if file_name not in listdir():
            self.master_fid = None
            return

        f = open(file_name)
        cfg = loads(f.read())
        f.close()

        self.master_fid = bytearray(unhexlify(cfg["master_fid"].encode()))

    def set_master_fid(self, fid: bytearray) -> None:
        self.master_fid = fid
        self._save_config()

    def io(self) -> None:
        pass
