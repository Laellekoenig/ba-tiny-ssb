from .feed import get_children, length, get_want, get_feed, FEED
from .feed_manager import FeedManager
from .html import Holder as HTMLHolder
from .http import Holder as HTTPHolder
from .http import run_http
from .util import PYCOM, listdir
from .version_manager import VersionManager
from _thread import start_new_thread, allocate_lock
from sys import platform
from os import urandom
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
        "master_fid",
        "queue",
        "queue_lock",
        "group",
        "http",
        "version_manager",
        "prev_send",
        "prev_send_lock",
        "this",
    )

    def __init__(self, enable_http: bool = False) -> None:
        self.feed_manager = FeedManager()
        self.master_fid = None
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
        self.this = urandom(8)

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

    def set_master_feed(self, feed: struct[FEED]) -> None:
        self.master_fid = feed.fid
        if length(feed) >= 2:
            update_fid = get_children(feed)[1]
            assert type(update_fid) is bytearray
            self.version_manager.set_update_feed(update_fid)

        self._save_config()

    def _start_version_manager(self) -> None:
        if self.master_fid is None:
            return

        master_feed = get_feed(self.master_fid)
        children = get_children(master_feed)
        if len(children) < 2:
            return

        update_fid = children[1]
        assert type(update_fid) is bytearray
        self.version_manager.set_update_feed(update_fid)

    def _listen(self, sock: socket) -> None:
        while True:
            msg, _ = sock.recvfrom(1024)
            if msg[:8] == bytes(self.this):
                continue

            msg = msg[8:]
            msg_len = len(msg)

            if msg_len > 128:
                print("message too long, discarded")
                continue

            # packet request
            if msg_len == 43 or msg_len == 63:
                tpl = self.feed_manager.consult_dmx(bytearray(msg[:7]))
                if tpl:
                    print("received request")
                    fn, fid = tpl
                    req_wire = fn(fid, msg)
                    with self.queue_lock:
                        if req_wire is not None:
                            self.queue.insert(0, req_wire)
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
                
                hash = bytearray(20)
                hash[:] = sha256(msg[8:]).digest()[:20]
                print(hash)
                tpl = self.feed_manager.consult_dmx(hash)
                if tpl:
                    print("blob in dmx")
                    fn, fid = tpl
                    fn(fid, msg)

                    with self.queue_lock:
                        self.queue.insert(0, get_want(get_feed(fid)))
                        continue
            else:
                print("received invalid packet")

    def _send(self, sock: socket) -> None:
        while True:
            with self.queue_lock:
                if self.queue:
                    msg = self.queue.pop(0)
                    try:
                        sock.sendto(self.this + msg, self.group)
                    except:
                        print("error send: ", type(msg))
                    with self.prev_send_lock:
                        self.prev_send = bytes(msg)
            sleep(0.4)

    def _fill_wants(self) -> None:
        while True:
            with self.queue_lock:
                if not self.queue:
                    for fid in self.feed_manager.listfids():
                        if bytes(fid) not in self.feed_manager.keys:
                            want = get_want(get_feed(fid))
                            if want:
                                self.queue.append(want)
            sleep(0.5)

    def io(self) -> None:
        if PYCOM:
            if self.http:
                print("starting http server...")
                server_sock = socket(AF_INET, SOCK_STREAM)
                server_sock.setsockopt(SOL_SOCKET, SO_REUSEADDR, 1)
                server_sock.bind(getaddrinfo("0.0.0.0", 80)[0][-1])
                server_sock.listen(1)
                run_http(server_sock)
        
        else:
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

            start_new_thread(self._fill_wants, ())

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
