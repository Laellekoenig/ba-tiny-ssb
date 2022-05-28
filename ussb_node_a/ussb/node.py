from .feed import get_children, length, get_want, get_feed, FEED
from .feed_manager import FeedManager
from .html import Holder as HTMLHolder
from .http import Holder as HTTPHolder
from .http import run_http
from .util import listdir
from .version_manager import VersionManager
from _thread import start_new_thread, allocate_lock
from sys import maxsize, platform
from json import dumps, loads
from hashlib import sha256
from time import sleep
from ubinascii import hexlify, unhexlify
from uctypes import struct
from usocket import (
    socket,
    AF_INET,
    SOCK_STREAM,
    SOL_SOCKET,
    SO_REUSEADDR,
    getaddrinfo,
    SOCK_DGRAM,
)


class Node:

    __slots__ = (
        "feed_manager",
        "master_feed",
        "queue",
        "queue_lock",
        "group",
        "http",
        "version_manager",
        "prev_send",
        "prev_send_lock",
    )

    def __init__(self, enable_http: bool = False) -> None:
        self.feed_manager = FeedManager()
        self.master_feed = None
        self._load_config()
        self.queue_lock = allocate_lock()
        self.queue = []
        self.group = getaddrinfo("224.1.1.1", 5000)[0][-1]
        self.http = enable_http
        self.version_manager = VersionManager(self.feed_manager)
        self.prev_send_lock = allocate_lock()
        self.prev_send = None
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

    def _start_version_manager(self) -> None:
        if self.master_feed is None:
            return

        children = get_children(self.master_feed)
        if len(children) < 2:
            return

        update_fid = children[1]
        assert type(update_fid) is bytearray
        update_feed = get_feed(update_fid)
        assert update_feed is not None

        self.version_manager.set_update_feed(update_feed)

    def _listen(self, sock: socket) -> None:
        while True:
            msg, _ = sock.recvfrom(1024)
            # if port == own:
                # continue

            with self.prev_send_lock:
                if msg == self.prev_send:
                    continue

            msg_len = len(msg)

            if msg_len > 128:
                print("message too long, discarded")
                continue


            # packet request
            if msg_len == 43:
                tpl = self.feed_manager.consult_dmx(bytearray(msg[:7]))
                if tpl:
                    print("received request")
                    fn, fid = tpl
                    req_wire = fn(fid, msg)
                    with self.queue_lock:
                        self.queue.append(req_wire)
                    continue

            # packet
            elif msg_len == 128:
                tpl = self.feed_manager.consult_dmx(bytearray(msg[8:15]))
                if tpl:
                    print("received packet")
                    fn, fid = tpl
                    fn(fid, msg)

                    if not self.version_manager.is_configured():
                        self._start_version_manager()

                    with self.queue_lock:
                        self.queue.insert(0, get_want(get_feed(fid)))
                    continue

            # FIX: ignore reserved 8B?
            else:
                blob_ptr = bytearray(sha256(msg).digest()[:20])
                # blob
                tpl = self.feed_manager.consult_dmx(blob_ptr)
                if tpl: 
                    print("received blob")
                    fn, fid = tpl
                    fn(fid, bytearray(msg))

    def _send(self, sock: socket) -> None:
        while True:
            msg = None
            with self.queue_lock:
                if len(self.queue) > 0:
                    msg = self.queue.pop(0)
                else:
                    for fid in self.feed_manager.fids:
                        if bytes(fid) not in self.feed_manager.keys:
                            self.queue.append(get_want(get_feed(fid)))
                    continue

            if msg is None:
                continue

            sock.sendto(msg, self.group)
            with self.prev_send_lock:
                self.prev_send = bytes(msg)
            sleep(0.2)  # add some delay

    def io(self) -> None:
        # http socket
        tx = socket(AF_INET, SOCK_DGRAM)
        tx.bind(getaddrinfo("0.0.0.0", 0)[0][-1])

        start_new_thread(self._send, (tx,))

        rx = socket(AF_INET, SOCK_DGRAM)
        rx.setsockopt(SOL_SOCKET, SO_REUSEADDR, 1)
        rx.bind(self.group)
        if platform == "darwin":
            mreq = bytes([int(i) for i in "224.1.1.1".split(".")]) + bytes(4)
            rx.setsockopt(0, 12, mreq)

        if self.http:
            start_new_thread(self._listen, (rx,))

            print("starting http server...")
            server_sock = socket(AF_INET, SOCK_STREAM)
            server_sock.setsockopt(SOL_SOCKET, SO_REUSEADDR, 1)
            server_sock.bind(getaddrinfo("0.0.0.0", 8000)[0][-1])
            server_sock.listen(1)
            run_http(server_sock)
        else:
            self._listen(rx)
