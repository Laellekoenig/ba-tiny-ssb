from .feed import get_children, length, get_want, get_feed, FEED
from .feed_manager import FeedManager
from .html import Holder as HTMLHolder
from .http import Holder as HTTPHolder
from .http import run_http
from .util import listdir
from .version_manager import VersionManager
from json import dumps, loads
from time import sleep
from ubinascii import hexlify, unhexlify
from uctypes import struct
from usocket import socket, AF_INET, SOCK_STREAM, SOL_SOCKET, SO_REUSEADDR, getaddrinfo


class Node:

    __slots__ = (
        "feed_manager",
        "master_feed",
        "queue",
        "group",
        "http",
        "version_manager",
    )

    def __init__(self, enable_http: bool = False) -> None:
        self.feed_manager = FeedManager()
        self.master_feed = None
        self._load_config()
        self.queue = []
        self.group = ("224.1.1.1", 5000)
        self.http = enable_http
        self.version_manager = VersionManager(self.feed_manager)
        # FIXME: bodge
        HTTPHolder.vm = self.version_manager
        HTMLHolder.vm = self.version_manager

    def __del__(self) -> None:
        self._save_config()

    def _save_config(self) -> None:
        if self.master_feed is None:
            return

        cfg = {"master_fid": hexlify(bytes(self.master_feed.fid)).decode()}
        f = open("node_cfg.json", "w")
        f.write(dumps(cfg))
        f.close()

    def _load_config(self) -> None:
        file_name = "node_cfg.json"
        if file_name not in listdir():
            self.master_feed = None
            return

        f = open(file_name)
        cfg = loads(f.read())
        f.close()

        master_fid = bytearray(unhexlify(cfg["master_fid"].encode()))
        self.master_feed = get_feed(master_fid)

    def set_master_feed(self, feed: struct[FEED]) -> None:
        self.master_feed = feed
        if length(feed) >= 2:
            update_fid = get_children(feed)[1]
            assert type(update_fid) is bytearray
            update_feed = get_feed(update_fid)
            self.version_manager.set_update_feed(update_feed)

        self._save_config()

    def _listen(self, sock: socket, own: int) -> None:
        while True:
            msg, (_, port) = sock.recvfrom(1024)
            if port == own:
                continue

            # todo handle message
            print(msg)

    def _send(self, sock: socket) -> None:
        not_own_feed = lambda fid: fid not in self.feed_manager.keys
        while True:
            msg = None
            if len(self.queue) > 0:
                msg = self.queue.pop(0)

            if msg is None:
                continue

            sock.sendto(msg, self.group)
            # update queue, this can be heavily optimized
            wants = [
                get_want(get_feed(fid))
                for fid in filter(not_own_feed, self.feed_manager.listfids())
            ]

            for want in wants:
                if want not in self.queue:
                    self.queue.append(want)

            sleep(0.2)  # add some delay

    def io(self) -> None:
        # http socket
        if self.http:
            print("starting http server...")
            server_sock = socket(AF_INET, SOCK_STREAM)
            server_sock.setsockopt(SOL_SOCKET, SO_REUSEADDR, 1)
            server_sock.bind(getaddrinfo("0.0.0.0", 8000)[0][-1])
            server_sock.listen(1)
            run_http(server_sock)
