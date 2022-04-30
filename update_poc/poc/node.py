import os
import sys
import time
import socket
import struct
import json
from hashlib import sha256
import _thread
from tinyssb.feed_manager import FeedManager
from tinyssb.ssb_util import to_hex, from_hex
from .version_manager import VersionManager

# non-micropython import
if sys.implementation.name != "micropython":
    # Optional type annotations are ignored in micropython
    from typing import Union


class Node:

    parent_dir = "data"
    multicast_group = ("224.1.1.1", 5000)

    def __init__(self, name: str) -> None:
        self.name = name
        self.path = self.parent_dir + "/" + name
        # setup directories
        self._create_dirs()
        # create feed manager (directories exist)
        self.feed_manager = FeedManager(self.path)
        self.version_manager = VersionManager(self.path + "/code",
                                              self.feed_manager)
        self.master_fid = None
        # load config
        self.load_config()

        # threading
        self.queue = []
        self.queue_lock = _thread.allocate_lock()

    def _create_dirs(self) -> None:
        if self.parent_dir not in os.listdir():
            os.mkdir(self.parent_dir)
        assert self.path is not None, "call class first"
        if self.name not in os.listdir(self.parent_dir):
            os.mkdir(self.path)
        if "code" not in os.listdir(self.path):
            os.mkdir(self.path + "/code")

    def _start_version_control(self) -> bool:
        if self.master_fid is None:
            return False

        # get master feed
        master_feed = self.feed_manager.get_feed(from_hex(self.master_fid))
        if master_feed is None:
            return False

        # check if update feed already exists -> second child
        children = master_feed.get_children()
        if len(children) < 2:
            return False

        update_feed = self.feed_manager.get_feed(children[1])

        # configure and start version manager
        self.version_manager.set_update_feed(update_feed)
        return True

    def load_config(self) -> None:
        file_name = "config.json"
        file_path = self.path + "/" + file_name
        config = None
        if file_name not in os.listdir(self.path):
            # config does not exist yet, create json file containing None
            f = open(file_path, "w")
            f.write(json.dumps(None))
            f.close()
        else:
            # file exists -> read file
            f = open(file_path, "r")
            json_string = f.read()
            f.close()
            config = json.loads(json_string)

        if config is None:
            keys = {}
            master_fid = None
        else:
            keys = config["keys"]
            master_fid = config["master_fid"]

        # load keys into feed manager
        self.feed_manager.update_keys(keys)
        self.master_fid = master_fid

        # start version control
        if not self.version_manager.is_configured():
            self._start_version_control()

    def __del__(self):
        self.save_config()

    def set_master_fid(self, fid: Union[bytes, str]) -> None:
        if type(fid) is bytes:
            fid = to_hex(fid)
        self.master_fid = fid
        self.save_config()

    def save_config(self) -> None:
        config = {}
        config["keys"] = self.feed_manager.keys
        config["master_fid"] = self.master_fid

        f = open(self.path + "/config.json", "w")
        f.write(json.dumps(config))
        f.close()

    def _send(self, sock: socket.socket) -> None:
        # ask for missing packets
        while True:
            msg = None
            self.queue_lock.acquire()
            if len(self.queue) > 0:
                msg = self.queue[0]
                self.queue = self.queue[1:]
            self.queue_lock.release()
            if msg is not None:
                # add reserved 8B
                msg = bytes(8) + msg
                sock.sendto(msg, self.multicast_group)
            time.sleep(.2)

    def _listen(self, sock: socket.socket, own: int) -> None:
        # listen for incoming messages
        while True:
            try:
                msg, (_, port) = sock.recvfrom(1024)
            except Exception:
                # timeout
                continue
            if port == own:
                continue
            # new message
            msg = msg[8:] # cut off reserved 8B
            msg_hash = sha256(msg).digest()[:20]
            # check if message is blob
            tpl = self.feed_manager.consult_dmx(msg_hash)
            if tpl is not None:
                # blob
                (fn, fid) = tpl  # unpack
                fn(fid, msg)  # call
                continue

            # not a blob
            dmx = msg[:7]
            tpl = self.feed_manager.consult_dmx(dmx)
            if tpl is not None:
                (fn, fid) = tpl  # unpack
                requested_wire = fn(fid, msg)
                # check if version control already running
                if not self.version_manager.is_configured():
                    self._start_version_control()
                if requested_wire is not None:
                    # was request
                    self.queue_lock.acquire()
                    self.queue.append(requested_wire)
                    self.queue_lock.release()

    def _want_feeds(self):
        while True:
            wants = []
            for feed in self.feed_manager:
                if to_hex(feed.fid) not in self.feed_manager.keys:
                    # not 'own' feed -> request next packet
                    wants.append(feed.get_want())

            # now append to queue
            self.queue_lock.acquire()
            for want in wants:
                if want not in self.queue:
                    self.queue.append(want)
            self.queue_lock.release()
            time.sleep(1.5)

    def io(self) -> None:
        # create sockets
        s_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s_sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        s_sock.bind(("", 0))
        # for now use port number to filter out own messages
        _, port = s_sock.getsockname()

        r_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        r_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        r_sock.bind(self.multicast_group)
        r_sock.settimeout(3)
        mreq = struct.pack("=4sl",
                           socket.inet_aton("224.1.1.1"),
                           socket.INADDR_ANY)
        r_sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)

        _thread.start_new_thread(self._listen, (r_sock, port, ))

        _thread.start_new_thread(self._send, (s_sock,))

        # keep main thread alive
        self._want_feeds()
