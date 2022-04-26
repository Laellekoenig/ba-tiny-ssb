import os
import threading
import time
import socket
import struct
import json
from hashlib import sha256
from threading import Thread
from typing import Dict, Optional, Union
from tinyssb.feed_manager import FeedManager
from tinyssb.packet import PacketType
from tinyssb.feed import Feed
import pure25519
from tinyssb.ssb_util import from_hex, to_hex
from .version_manager import VersionManager


stop_threads = False


class Node:

    parent_dir = "data"
    multicast_group = ("224.1.1.1", 5000)

    def __init__(self, name: str):
        self.name = name
        self.path = self.parent_dir + "/" + name
        self._create_directoty()

        # things loaded by config file
        self.init_keys = {}
        self.master_fid = None
        self.load_config()
        self.feed_manager = FeedManager(self.path, keys=self.init_keys)

        self.queue = []
        self.queue_lock = threading.Lock()
        self.dmx_table = {}
        self.dmx_lock = threading.Lock()
        self._fill_dmx()
        self.chain_table = {}
        self.chain_lock = threading.Lock()
        self._fill_chain()

        # update specific
        if self.master_fid is None:
            # when initializing files
            self.version_manager = None
        else:
            update_feed = self.feed_manager.get_feed(self.master_fid)
            self.version_manager = VersionManager(self.path + "/code",
                                                  self.feed_manager,
                                                  update_feed)

    def _fill_dmx(self) -> None:
        self.dmx_lock.acquire()
        self.dmx_table = {}
        for feed in self.feed_manager:
            # add both want and request dmxes to table
            want = feed.get_want()[:7]
            next_dmx = feed.get_next_dmx()

            self.dmx_table[want] = (self._handle_want, feed.fid)
            self.dmx_table[next_dmx] = (self._handle_packet, feed.fid)
        self.dmx_lock.release()

    def _fill_chain(self) -> None:
        self.chain_lock.acquire()
        self.chain_table = {}
        for feed in self.feed_manager:
            blob_ptr = feed.waiting_for_blob()
            if blob_ptr is not None:
                self.chain_table[blob_ptr] = feed.fid
        self.chain_lock.release()

    def _handle_blob(self, fid: bytes, blob: bytes, signature: bytes) -> None:
        print(f"received blob")
        feed = self.feed_manager.get_feed(fid)
        assert feed is not None, "failed to get feed"

        # insert
        if not feed.verify_and_append_blob(blob):
            print("blob could not be verified")
            return

        # update table: remove old pointer
        self.chain_lock.acquire()
        self.chain_table.pop(signature, None)
        self.chain_lock.release()

        # check if blob has ended
        next_ptr = feed.waiting_for_blob()
        if next_ptr is None:
            print("end of blob")
            print(feed[-1])
            self.dmx_lock.acquire()
            # add dmx for next packet
            self.dmx_table[feed.get_next_dmx()] = (self._handle_packet, fid)
            self.dmx_lock.release()
            return

        # add next pointer to table
        self.chain_lock.acquire()
        self.chain_table[next_ptr] = fid
        self.chain_lock.release()

    def _handle_want(self, fid: bytes, request: bytes) -> None:
        print(f"received want: {to_hex(fid)}")

        seq = int.from_bytes(request[39:43], "big")
        requested_feed = self.feed_manager.get_feed(fid)
        if requested_feed.front_seq < seq:
            # packet does not exist yet
            return

        requested_wire = None
        if len(request) == 43:
            print("want regular")
            # regular feed entry request
            requested_wire = requested_feed.get_wire(seq)
            if requested_wire is None:
                print("pkt does not exist yet")
                return
        if len(request) == 63:
            print("want blob")
            # blob request
            blob_ptr = request[-20:]
            requested_blob = requested_feed._get_blob(blob_ptr)
            if requested_blob is None:
                print("did not find blob")
                # blob not found
                return
            requested_wire = requested_blob.wire

        assert requested_wire is not None, "invalid request"
        # append to queue
        self.queue_lock.acquire()
        self.queue.append(requested_wire)
        self.queue_lock.release()

    def _handle_packet(self, fid: bytes, wire: bytes) -> None:
        print("packet arrived")
        feed = self.feed_manager.get_feed(fid)
        feed.verify_and_append_bytes(wire)

        front_type = feed.get_type(-1)
        blob_ptr = feed.waiting_for_blob()
        if front_type == PacketType.chain20 and blob_ptr is not None:
            # unfinished blob
            print("unfinished blob")
            self.chain_lock.acquire()
            self.chain_table[blob_ptr] = fid
            self.chain_lock.release()
            return

        print(feed[-1])

        # update dmx values and clean up queue
        next_dmx = feed.get_next_dmx()
        if next_dmx == wire[:7]:
            # nothing was appended
            return

        # check if new contn or child feed should be created
        new_fid = wire[8:40]
        if front_type == PacketType.mkchild:
            print("make child feed")
            _ = self.feed_manager.create_feed(new_fid,
                                              parent_seq = feed.front_seq,
                                              parent_fid = feed.fid)
            # update dmx vals
            self._fill_dmx()
        if front_type == PacketType.contdas:
            print("make continuation feed")

        self.dmx_lock.acquire()
        self.dmx_table.pop(wire[:7], None)  # remove old dmx value
        self.dmx_table[next_dmx] = (self._handle_packet, feed.fid)
        self.dmx_lock.release()

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

    def load_config(self) -> None:
        file_name = self.path + "/config.json"
        if "config.json" not in os.listdir(self.path):
            # config does not exist yet
            # this can be improved for first start up
            # create file
            f = open(file_name, "w")
            f.write(json.dumps(None))
            f.close()

        f = open(file_name, "r")
        json_string = f.read()
        f.close()

        config = json.loads(json_string)
        if config is None:
            self.keys = {}
            self.master_fid = None
            return

        self.init_keys = config["keys"]
        self.master_fid = config["master_fid"]

    def get_keys(self) -> Dict[bytes, bytes]:
        # check if file exists
        key_dict = {}
        if "keys" not in os.listdir(self.path):
            return key_dict
        else:
            f = open(self.path + "/keys", "rb")
            raw_keys = f.read()
            f.close()
            assert len(raw_keys) % 64 == 0

            # go over bytes
            while len(raw_keys) != 0:
                fid = to_hex(raw_keys[:32])
                skey = to_hex(raw_keys[32:64])
                key_dict[fid] = skey
                raw_keys = raw_keys[64:]

            return key_dict

    def save_keys(self) -> None:
        f = open(self.path + "/keys", "wb")
        f.seek(0)

        key_dict = self.feed_manager.keys
        for fid in key_dict:
            skey = key_dict[fid]
            f.write(from_hex(fid))
            f.write(from_hex(skey))

    def _create_directoty(self) -> None:
        if self.parent_dir not in os.listdir():
            os.mkdir(self.parent_dir)
        if self.name not in os.listdir(self.parent_dir):
            os.mkdir(self.path)
        if "code" not in os.listdir(self.path):
            os.mkdir(self.path + "/code")

    def create_feed(self) -> Optional[Feed]:
        assert self.feed_manager is not None, "initialize feed manager fist"
        key, _ = pure25519.create_keypair()
        skey = key.sk_s[:32]
        vkey = key.vk_s
        feed = self.feed_manager.create_feed(vkey, skey)
        # self.save_keys()
        self.save_config()
        return feed

    def create_child_feed(self, parent: Union[Feed, bytes]) -> Optional[Feed]:
        assert self.feed_manager is not None, "initialize feed manager fist"
        key, _ = pure25519.create_keypair()
        skey = key.sk_s[:32]
        vkey = key.vk_s
        feed = self.feed_manager.create_child_feed(parent, vkey, skey)
        # self.save_keys()
        self.save_config()
        return feed

    def create_contn_feed(self, parent: Union[Feed, bytes]) -> Optional[Feed]:
        assert self.feed_manager is not None, "initialize feed manager fist"
        key, _ = pure25519.create_keypair()
        skey = key.sk_s[:32]
        vkey = key.vk_s
        feed = self.feed_manager.create_contn_feed(parent, vkey, skey)
        # self.save_keys()
        self.save_config()
        return feed

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
            time.sleep(2)

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
            msg_hash = sha256(msg).digest()[:20]  # maybe check if table empty
            # check if message is blob
            self.chain_lock.acquire()
            try:
                fid = self.chain_table[msg_hash]
                self.chain_lock.release()
                self._handle_blob(fid, msg, msg_hash)
                continue
            except Exception:
                self.chain_lock.release()

            dmx = msg[:7]
            self.dmx_lock.acquire()
            try:
                fn, fid = self.dmx_table[dmx]
                self.dmx_lock.release()
                # now give message to handler
                fn(fid, msg)
            except Exception:
                # dmx value not found
                self.dmx_lock.release()

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
            time.sleep(10)

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
