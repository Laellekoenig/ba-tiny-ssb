import os
import threading
import time
import socket
import struct
import json
from hashlib import sha256
from threading import Thread
from typing import Union
from tinyssb.feed_manager import FeedManager
from tinyssb.ssb_util import to_hex


stop_threads = False


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
        # load config
        self.load_config()

        # threading
        self.queue = []
        self.queue_lock = threading.Lock()

        # TODO
        self.master_fid = None
        self.version_manager = None

    def _create_dirs(self) -> None:
        if self.parent_dir not in os.listdir():
            os.mkdir(self.parent_dir)
        assert self.path is not None, "call class first"
        if self.name not in os.listdir(self.parent_dir):
            os.mkdir(self.path)
        if "code" not in os.listdir(self.path):
            os.mkdir(self.path + "/code")

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
        self.feed_manager.keys = keys
        self.master_fid = master_fid

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
        global stop_threads
        while not stop_threads:
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
            time.sleep(1)

    def _listen(self, sock: socket.socket, own: int) -> None:
        # listen for incoming messages
        global stop_threads
        while not stop_threads:
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
                if requested_wire is not None:
                    # was request
                    self.queue_lock.acquire()
                    self.queue.append(requested_wire)
                    self.queue_lock.release()

    def _want_feeds(self):
        global stop_threads
        while not stop_threads:
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
            time.sleep(5)

    def _user_cmds(self) -> None:
        global stop_threads
        while not stop_threads:
            cmd = input()
            if cmd in ["q", "quit"]:
                stop_threads = True

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

        t = Thread(target=self._listen, args=(r_sock, port,))
        t.start()

        t2 = Thread(target=self._send, args=(s_sock,))
        t2.start()

        # not ideal solution, but should suffice for poc
        t3 = Thread(target=self._want_feeds)
        t3.start()

        # for handling user input
        t4 = Thread(target=self._user_cmds)
        t4.start()
