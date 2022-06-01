from .feed import get_children, length, get_want, get_feed, FEED
from .feed_manager import FeedManager
from .html import Holder as HTMLHolder
from .http import Holder as HTTPHolder
from .http import run_http
from .util import PYCOM, listdir
from .version_manager import VersionManager
from .visualizer import Visualizer
from _thread import start_new_thread, allocate_lock
from hashlib import sha256
from json import dumps, loads
from os import urandom
from sys import platform
from time import sleep
from ubinascii import hexlify, unhexlify
from uctypes import struct
from usocket import (
    AF_INET,
    SOCK_DGRAM,
    SOCK_STREAM,
    SOL_SOCKET,
    SO_REUSEADDR,
    getaddrinfo,
    socket,
)


if PYCOM:
    from socket import AF_LORA, SOCK_RAW


class Node:
    """
    Contains the main I/O logic of the device.
    Starts the version manager (once possible) and requests/accepts
    new packets from other nodes.
    Also opens a http server, where the web GUI is served.
    This is disabled by default and can be activated by passing
    enable_http=True in the constructor.
    """

    # minor performance boost
    __slots__ = (
        "feed_manager",
        "group",
        "http",
        "master_fid",
        "prev_send",
        "prev_send_lock",
        "queue",
        "queue_lock",
        "this",
        "version_manager",
        "viz",
    )

    def __init__(self, enable_http: bool = False) -> None:
        self.feed_manager = FeedManager()
        self.master_fid = None
        self._load_config()

        # queue containing outgoing messages and requests
        self.queue_lock = allocate_lock()
        self.queue = []

        # UDP group (not on pycom devices)
        self.group = getaddrinfo("224.1.1.1", 5000)[0][-1]
        self.http = enable_http
        self.version_manager = VersionManager(self.feed_manager)

        # FIXME: bodge to avoid circular imports
        HTTPHolder.vm = self.version_manager
        HTMLHolder.vm = self.version_manager

        # used when using UDP -> distinguish own messages from other node's messages
        # getaddrinfo does not work in my micropython implementation
        self.this = urandom(8)
        self.viz = None

    def __del__(self) -> None:
        self._save_config()

    def _save_config(self) -> None:
        """
        Saves the current master feed ID to a .json file.
        """
        if self.master_fid is None:
            return

        f = open("node_cfg.json", "w")
        f.write(dumps({"master_fid": hexlify(bytes(self.master_fid)).decode()}))
        f.close()

    def _load_config(self) -> None:
        """
        Loads the master feed ID from the .json file, if available.
        If no configuration file is found, it is set to None.
        """
        file_name = "node_cfg.json"

        if file_name not in listdir():
            self.master_fid = None
            return

        f = open(file_name)
        cfg = loads(f.read())
        f.close()

        self.master_fid = bytearray(unhexlify(cfg["master_fid"].encode()))

    def set_master_feed(self, feed: struct[FEED]) -> None:
        """
        Updates the node's master feed ID to the feed ID of the given feed.
        Also saves this new master feed ID to a .json file.
        """
        self.master_fid = feed.fid
        self._save_config()

        # check if the update feed is already available
        if length(feed) >= 2:
            # start version manager
            self._start_version_manager()

    def _start_version_manager(self) -> None:
        """
        Starts the version manager if the update feed is available.
        """
        if self.master_fid is None:
            return

        master_feed = get_feed(self.master_fid)
        children = get_children(master_feed)

        if len(children) >= 2:
            update_fid = children[1]
            assert type(update_fid) is bytearray
            self.version_manager.set_update_feed(update_fid)

    def _listen(self, sock: socket) -> None:
        """
        Listens for incoming UDP messages and filters out own messages using the
        random self.this bytes. NOT used with LoRa on pycom devices.
        """
        while True:
            msg, _ = sock.recvfrom(1024)
            if msg[:8] == bytes(self.this):
                # own message
                continue
            self._handle_packet(msg[8:])

    def _handle_packet(self, msg: bytes) -> None:
        """
        Used for handling incoming messages.
        After a new packet is appended, the request for the next packet/blob
        in the feed is inserted at the first position of the queue (greedy).
        Runs on pycom and in UNIX.
        Registers actions to the visualizer (not on pycom).
        """
        msg_len = len(msg)

        if msg_len > 128:
            print("message discarded, too long")
            return

        # packet or blob request
        if msg_len == 43 or msg_len == 63:
            tpl = self.feed_manager.consult_dmx(bytearray(msg[:7]))
            if tpl:
                fn, fid = tpl

                # register action in visualizer
                if self.viz:
                    self.viz.register_rx(fid)

                # prepend requested packet/blob to queue
                req_wire = fn(fid, bytearray(msg))
                if req_wire:
                    with self.queue_lock:
                        self.queue.insert(0, req_wire)
                return

        # new packet or blob
        elif msg_len == 128:
            # check packet first -> avoid hashing for regular packets
            tpl = self.feed_manager.consult_dmx(bytearray(msg[8:15]))
            if tpl:
                fn, fid = tpl

                # register action in visualizer
                if self.viz:
                    self.viz.register_rx(fid)

                # execute handler
                # FIXME: can/should this be done in a new thread?
                fn(fid, bytearray(msg))

                # maybe new packet contains update feed -> start version manager
                if not self.version_manager.is_configured():
                    self._start_version_manager()

                # prepend want to next packet of feed (greedy)
                with self.queue_lock:
                    self.queue.insert(0, get_want(get_feed(fid)))
                return

            # not a packet -> check whether it is a blob
            # check if hash is in table
            hash = bytearray(sha256(msg[8:]).digest()[:20])

            tpl = self.feed_manager.consult_dmx(hash)
            if tpl:
                fn, fid = tpl

                # register action in visualizer
                if self.viz:
                    self.viz.register_rx(fid)

                # execute handler
                # FIXME: can/should this be done in a new thread?
                fn(fid, bytearray(msg))

                # prepend want to next packet/blob of feed (greedy)
                with self.queue_lock:
                    self.queue.insert(0, get_want(get_feed(fid)))
                    return
        else:
            print("received invalid packet")

    def _send(self, sock: socket) -> None:
        """
        Removes the first item of the queue and sends it via UDP.
        Not used on pycom devices.
        """
        while True:
            msg = None
            with self.queue_lock:
                # check if queue is empty
                if self.queue:
                    msg = self.queue.pop(0)

            if msg is None:
                continue

            # register action in visualizer
            if self.viz:
                # check which feed the dmx value belongs to (want)
                tpl = self.feed_manager.consult_dmx(msg[:7])
                if tpl:
                    _, fid = tpl
                    self.viz.register_tx(fid)
                else:
                    # check which feed the dmx value belongs to (packet/blob)
                    tpl = self.feed_manager.consult_dmx(msg[8:15])
                    if tpl:
                        _, fid = tpl
                        self.viz.register_tx(fid)

            # now actually send message
            try:
                sock.sendto(self.this + msg, self.group)
            except:
                print("error send: ", type(msg))
            sleep(0.4)

    def _lora_loop(self, sock: socket) -> None:
        """
        Lora RX/TX loop. Only run on pycom devices.
        Unlike with UDP, sending and receiving is handled in a single loop.
        """
        sock.setblocking(False)
        while True:
            msg = None

            # get next message
            with self.queue_lock:
                if self.queue:
                    msg = self.queue.pop(0)

            # send message
            if msg:
                try:
                    sock.send(msg)
                except Exception:
                    print("failed to send")

            # FIXME: remove this sleep
            sleep(0.5)

            # check for incoming messages
            msg = sock.recv(128)
            if len(msg) == 0:
                continue

            # DEBUG
            print("new msg!: {}".format(msg))

            self._handle_packet(msg)
            # check if there is an update to apply (pycom bodge, fix stack overflows)
            self.version_manager.execute_updates()

    def _fill_wants(self) -> None:
        """
        Periodically checks if the queue is empty.
        If so, it is filled with wants for every locally saved feed
        (for which no key is found -> consumer).
        """
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
        """
        Main method of the node.
        Starts the correct RX/TX methods, depending on the device.
        Also starts a http server with the web GUI if specified in constructor.
        """
        if PYCOM:
            # visualizer is disabled for performance reasons
            # LoRa on pycom devices
            sock = socket(AF_LORA, SOCK_RAW)
            start_new_thread(self._fill_wants, ())

            if self.http:
                # http server at address 192.168.4.1:80
                start_new_thread(self._lora_loop, (sock,))
                print("starting http server...")
                server_sock = socket(AF_INET, SOCK_STREAM)
                server_sock.setsockopt(SOL_SOCKET, SO_REUSEADDR, 1)
                server_sock.bind(getaddrinfo("0.0.0.0", 80)[0][-1])
                run_http(server_sock)
            else:
                self._lora_loop(sock)

        else:
            viz = Visualizer()
            self.viz = viz

            # sending socket
            tx = socket(AF_INET, SOCK_DGRAM)
            tx.bind(getaddrinfo("0.0.0.0", 0)[0][-1])
            start_new_thread(self._send, (tx,))

            # receiving socket
            rx = socket(AF_INET, SOCK_DGRAM)
            rx.setsockopt(SOL_SOCKET, SO_REUSEADDR, 1)
            rx.bind(self.group)
            if platform == "darwin":
                mreq = bytes([int(i) for i in "224.1.1.1".split(".")]) + bytes(4)
                rx.setsockopt(0, 12, mreq)
            start_new_thread(self._fill_wants, ())

            if self.http:
                # http server at address localhost:8000
                start_new_thread(self._listen, (rx,))
                print("starting http server...")
                server_sock = socket(AF_INET, SOCK_STREAM)
                server_sock.setsockopt(SOL_SOCKET, SO_REUSEADDR, 1)

                port = 8000
                while True:
                    # if port 8000 is not available, search for next available port
                    try:
                        server_sock.bind(getaddrinfo("0.0.0.0", port)[0][-1])
                        print("http server open on port {}".format(port))
                        break
                    except Exception:
                        port += 1

                run_http(server_sock, viz=viz)
            else:
                self._listen(rx)
