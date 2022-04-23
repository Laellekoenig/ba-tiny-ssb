import os
import threading
import time
import socket
import struct
from threading import Thread
from typing import Dict, Optional, Union
from tinyssb.feed_manager import FeedManager
from tinyssb.packet import PacketType
from tinyssb.feed import Feed
import pure25519
from tinyssb.ssb_util import from_hex, to_hex


stop_threads = False


class Node:

    parent_dir = "data"
    multicast_group = ("224.1.1.1", 5000)

    def __init__(self, name: str):
        self.name = name
        self.path = self.parent_dir + "/" + name
        self._create_directoty()
        self.keys = self.get_keys()
        self.feed_manager = FeedManager(self.path, keys=self.keys)
        self.queue = []
        self.queue_lock = threading.Lock()
        self.dmx_table = {}
        self.dmx_lock = threading.Lock()
        self._fill_dmx()

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

    def _handle_want(self, fid: bytes, request: bytes) -> None:
        print(f"received want: {to_hex(fid)}")
        seq = int.from_bytes(request[-4:], "big")
        requested_feed = self.feed_manager.get_feed(fid)
        if requested_feed.front_seq < seq:
            # packet does not exist yet
            return

        requested_wire = requested_feed.get_wire(seq)
        if requested_wire is None:
            print("pkt does not exist yet")
            return

        # append to queue
        self.queue_lock.acquire()
        self.queue.append(requested_wire)
        self.queue_lock.release()

    def _handle_packet(self, fid: bytes, wire: bytes) -> None:
        print("packet arrived")
        feed = self.feed_manager.get_feed(fid)
        feed.verify_and_append_bytes(wire)
        print(feed[-1])

        # update dmx values and clean up queue
        next_dmx = feed.get_next_dmx()
        if next_dmx == wire[:7]:
            # nothing was appended
            return

        # check if new contn or child feed should be created
        front_type = feed.get_type(-1)
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

    def create_feed(self) -> Optional[Feed]:
        assert self.feed_manager is not None, "initialize feed manager fist"
        key, _ = pure25519.create_keypair()
        skey = key.sk_s[:32]
        vkey = key.vk_s
        feed = self.feed_manager.create_feed(vkey, skey)
        self.save_keys()
        return feed

    def create_child_feed(self, parent: Union[Feed, bytes]) -> Optional[Feed]:
        assert self.feed_manager is not None, "initialize feed manager fist"
        key, _ = pure25519.create_keypair()
        skey = key.sk_s[:32]
        vkey = key.vk_s
        feed = self.feed_manager.create_child_feed(parent, vkey, skey)
        self.save_keys()
        return feed

    def create_contn_feed(self, parent: Union[Feed, bytes]) -> Optional[Feed]:
        assert self.feed_manager is not None, "initialize feed manager fist"
        key, _ = pure25519.create_keypair()
        skey = key.sk_s[:32]
        vkey = key.vk_s
        feed = self.feed_manager.create_contn_feed(parent, vkey, skey)
        self.save_keys()
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
            dmx = msg[:7]
            self.dmx_lock.acquire()
            try:
                fn, fid = self.dmx_table[dmx]
                self.dmx_lock.release()
            except Exception:
                # dmx value not found
                self.dmx_lock.release()
                continue

            # now give message to handler
            fn(fid, msg)

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
