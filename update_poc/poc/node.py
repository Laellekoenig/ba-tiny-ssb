import _thread
import json
import os
import socket
import struct
import sys
import time
from .version_manager import VersionManager
from hashlib import sha256
from tinyssb.feed_manager import FeedManager
from tinyssb.ssb_util import to_hex

# non-micropython import
if sys.implementation.name != "micropython":
    # Optional type annotations are ignored in micropython
    from typing import Union


class Node:
    """
    A very basic client for the tinyssb network.
    Uses UDP multicast to communicate with other nodes.
    The send queue is very naïve.
    """

    parent_dir = "data"
    multicast_group = ("224.1.1.1", 5000)
    cfg_file_name = "node_cfg.json"

    def __init__(self, name: str) -> None:
        self.name = name
        self.path = self.parent_dir + "/" + name
        # setup directories
        self._create_dirs()
        # create feed manager
        self.feed_manager = FeedManager(self.path)
        self.version_manager = VersionManager(self.path + "/code", self.feed_manager)
        self.master_fid = None
        # load configuration
        self._load_config()

        # support threading
        self.queue = []
        self.queue_lock = _thread.allocate_lock()

    def __del__(self):
        self.save_config()

    def _create_dirs(self) -> None:
        """
        Creates the basic directory structure of the node
        (if it does not exist yet).
        structure:
        data | node_a | _blobs
                      | _feeds
                      | code
        """
        if self.parent_dir not in os.listdir():
            os.mkdir(self.parent_dir)
        if self.name not in os.listdir(self.parent_dir):
            os.mkdir(self.path)
        if "code" not in os.listdir(self.path):
            os.mkdir(self.path + "/code")

    def _start_version_control(self) -> bool:
        """
        Completes the configuration of the version manager
        once the update feed is available.
        """
        if self.master_fid is None:
            return False

        # get master feed
        master_feed = self.feed_manager.get_feed(self.master_fid)
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

    def _load_config(self) -> None:
        """
        Loads the contents of the self.cfg_file_name file into this
        instance of the Node.
        The config contains the FIDs with associated keys and the FID
        of the master feed.
        """
        file_path = self.path + "/" + self.cfg_file_name
        config = None

        if self.cfg_file_name not in os.listdir(self.path):
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

    def save_config(self) -> None:
        """
        Writes the current master FID and FID-key-pairs into a json file.
        """
        config = {}
        config["keys"] = self.feed_manager.keys
        config["master_fid"] = self.master_fid

        f = open(self.path + "/" + self.cfg_file_name, "w")
        f.write(json.dumps(config))
        f.close()

    def set_master_fid(self, fid: Union[bytes, str]) -> None:
        """
        Used for manually setting this node's master feed.
        The provided FID may be a hex string or bytes.
        """
        if type(fid) is bytes:
            fid = to_hex(fid)
        self.master_fid = fid
        self.save_config()

    def _send(self, sock: socket.socket) -> None:
        """
        Infinite sending loop that removes the first item of the queue
        and sends it to the UDP multicast group.
        """
        while True:
            msg = None

            self.queue_lock.acquire()
            if len(self.queue) > 0:
                msg = self.queue.pop(0)  # remove first element
            self.queue_lock.release()

            if msg is not None:
                msg = bytes(8) + msg  # add reserved 8B
                sock.sendto(msg, self.multicast_group)

            time.sleep(0.2)

    def _listen(self, sock: socket.socket, own: int) -> None:
        """
        Infinite loop that listens for incoming messages and
        handles them depending on message type.
        """
        while True:
            try:
                msg, (_, port) = sock.recvfrom(1024)
            except Exception:
                continue  # timeout

            if port == own:
                continue  # ignore own messages

            # new message
            msg = msg[8:]  # cut off reserved 8B
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
                    # send requested packet -> add it to queue
                    self.queue_lock.acquire()
                    self.queue.append(requested_wire)
                    self.queue_lock.release()

    def _want_feeds(self):
        """
        Infinite loop that adds "wants" to the queue
        -> Asks for new feed entries.
        Very naïve implementation.
        """
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

    def user_input(self):
        while True:
            inpt = input()

            # handle different commands
            if inpt in ["p", "print"]:
                print(self.feed_manager)

            if inpt in ["e", "emergency"]:
                file_name = "example1.py"
                update = "print(\"hello emergency\")"
                self.version_manager.emergency_update_file(file_name, update)

            if inpt in ["c"]:
                call = self.feed_manager._callback
                new = {to_hex(k)[:8]: v for k, v in call.items()}
                print(new)

            if inpt in ["a", "apply"]:
                file_name = input("file name: ")
                seq = int(input("sequence number: "))
                self.version_manager.add_apply(file_name, seq)

            if inpt in ["sudo"]:
                cmd = input("cmd: ")
                exec(cmd)

    def io(self) -> None:
        """
        Starts one listening and one sending thread.
        """
        # sending sockets
        s_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s_sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        s_sock.bind(("", 0))
        # for now use port number to filter out own messages
        _, port = s_sock.getsockname()

        # receiving socket
        r_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        r_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        r_sock.bind(self.multicast_group)
        r_sock.settimeout(3)
        mreq = struct.pack("=4sl", socket.inet_aton("224.1.1.1"), socket.INADDR_ANY)
        r_sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)

        _thread.start_new_thread(self._listen, (r_sock, port,))
        _thread.start_new_thread(self._send, (s_sock,))
        _thread.start_new_thread(self.user_input, ())

        # keep main thread alive
        self._want_feeds()
