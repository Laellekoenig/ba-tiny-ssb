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

    name = None
    path = None
    feed_manager = None
    master_fid = None
    version_manager = None

    # threading
    queue = []
    queue_lock = threading.Lock()
    dmx_table = {}
    dmx_lock = threading.Lock()
    chain_table = {}
    chain_lock = threading.Lock()

    @classmethod
    def init(cls, name: str) -> None:
        cls.name = name
        cls.path = cls.parent_dir + "/" + name
        # setup directories
        cls._create_dirs()
        # create feed manager (directories exist)
        cls.feed_manager = FeedManager(cls.path)
        # load config
        cls.load_config()
        # fill dmx table
        cls._fill_dmx()
        # fill chain table
        cls._fill_chain()
        # start version manager
        cls.version_manager = VersionManager
        cls.version_manager.init(cls.path + "/code", cls.feed_manager)

    @classmethod
    def _create_dirs(cls) -> None:
        if cls.parent_dir not in os.listdir():
            os.mkdir(cls.parent_dir)
        assert cls.path is not None, "call class first"
        if cls.name not in os.listdir(cls.parent_dir):
            os.mkdir(cls.path)
        if "code" not in os.listdir(cls.path):
            os.mkdir(cls.path + "/code")

    @classmethod
    def load_config(cls) -> None:
        assert (cls.path is not None and
                cls.feed_manager is not None), "call clast first"
        file_name = "config.json"
        file_path = cls.path + "/" + file_name
        config = None
        if file_name not in os.listdir(cls.path):
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
        print("replacing feed_manager's keys")  # warning
        cls.feed_manager.keys = keys
        cls.master_fid = master_fid

    @classmethod
    def _fill_dmx(cls) -> None:
        assert cls.feed_manager is not None, "call class first"
        # reset table
        cls.dmx_lock.acquire()
        cls.dmx_table = {}

        for feed in cls.feed_manager:
            # add both want and request dmxes to table
            want = feed.get_want()[:7]
            next_dmx = feed.get_next_dmx()
            # set values
            cls.dmx_table[want] = (cls._handle_want, feed.fid)
            cls.dmx_table[next_dmx] = (cls._handle_packet, feed.fid)

        cls.dmx_lock.release()

    @classmethod
    def _fill_chain(cls) -> None:
        assert cls.feed_manager is not None, "call class first"
        cls.chain_lock.acquire()
        cls.chain_table = {}

        for feed in cls.feed_manager:
            blob_ptr = feed.waiting_for_blob()
            if blob_ptr is not None:
                cls.chain_table[blob_ptr] = feed.fid

        cls.chain_lock.release()

    @classmethod
    def _check_for_update_feed(cls) -> None:
        assert (cls.feed_manager is not None and
                cls.version_manager is not None), "call class first"

        master_feed = cls.feed_manager.get_feed(cls.master_fid)
        assert master_feed is not None, "failed to get master feed"

        children = master_feed.get_children()
        if len(children) >= 2:
            # second child is update feed
            update_fid = children[1]
            update_feed = cls.feed_manager.get_feed(update_fid)
            assert update_feed is not None, "failed to find master feed"
            cls.version_manager.set_update_feed(update_feed)

    @classmethod
    def _handle_blob(cls, fid: bytes, blob: bytes, signature: bytes) -> None:
        assert cls.feed_manager is not None, "call class first"
        print(f"received blob")
        feed = cls.feed_manager.get_feed(fid)
        assert feed is not None, "failed to get feed"

        # insert
        if not feed.verify_and_append_blob(blob):
            print("blob could not be verified")
            return

        # update table: remove old pointer
        cls.chain_lock.acquire()
        cls.chain_table.pop(signature, None)
        cls.chain_lock.release()

        # check if blob has ended
        next_ptr = feed.waiting_for_blob()
        if next_ptr is None:
            print("end of blob")
            print(feed[-1])
            cls.dmx_lock.acquire()
            # add dmx for next packet
            cls.dmx_table[feed.get_next_dmx()] = (cls._handle_packet, fid)
            cls.dmx_lock.release()
            return

        # add next pointer to table
        cls.chain_lock.acquire()
        cls.chain_table[next_ptr] = fid
        cls.chain_lock.release()

    @classmethod
    def _handle_want(cls, fid: bytes, request: bytes) -> None:
        assert cls.feed_manager is not None, "call class first"
        print(f"received want: {to_hex(fid)}")

        seq = int.from_bytes(request[39:43], "big")
        requested_feed = cls.feed_manager.get_feed(fid)
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
        cls.queue_lock.acquire()
        cls.queue.append(requested_wire)
        cls.queue_lock.release()

    @classmethod
    def _handle_packet(cls, fid: bytes, wire: bytes) -> None:
        assert (cls.feed_manager is not None and
                cls.version_manager is not None), "call class first"
        print("packet arrived")
        feed = cls.feed_manager.get_feed(fid)
        feed.verify_and_append_bytes(wire)

        front_type = feed.get_type(-1)
        blob_ptr = feed.waiting_for_blob()
        if front_type == PacketType.chain20 and blob_ptr is not None:
            # unfinished blob
            print("unfinished blob")
            cls.chain_lock.acquire()
            cls.chain_table[blob_ptr] = fid
            cls.chain_lock.release()
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
            _ = cls.feed_manager.create_feed(new_fid,
                                             parent_seq = feed.front_seq,
                                             parent_fid = feed.fid)

            # if update feed does not exist yet, check for it
            if cls.version_manager.update_feed is None:
                cls._check_for_update_feed()

            # update dmx vals
            cls._fill_dmx()
        if front_type == PacketType.contdas:
            print("make continuation feed")

        cls.dmx_lock.acquire()
        cls.dmx_table.pop(wire[:7], None)  # remove old dmx value
        cls.dmx_table[next_dmx] = (cls._handle_packet, feed.fid)
        cls.dmx_lock.release()

    @classmethod
    def set_master_fid(cls, fid: Union[bytes, str]) -> None:
        if type(fid) is bytes:
            fid = to_hex(fid)
        cls.master_fid = fid
        cls.save_config()

    @classmethod
    def save_config(cls) -> None:
        assert (cls.path is not None and
                cls.feed_manager is not None), "call class first"
        config = {}
        config["keys"] = cls.feed_manager.keys
        config["master_fid"] = cls.master_fid

        f = open(cls.path + "/config.json", "w")
        f.write(json.dumps(config))
        f.close()

    @classmethod
    def get_keys(cls) -> Dict[bytes, bytes]:
        assert cls.path is not None, "call class first"
        # check if file exists
        key_dict = {}
        if "keys" not in os.listdir(cls.path):
            return key_dict
        else:
            f = open(cls.path + "/keys", "rb")
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

    @classmethod
    def save_keys(cls) -> None:
        assert (cls.path is not None and
                cls.feed_manager is not None), "call class first"
        f = open(cls.path + "/keys", "wb")
        f.seek(0)

        key_dict = cls.feed_manager.keys
        for fid in key_dict:
            skey = key_dict[fid]
            f.write(from_hex(fid))
            f.write(from_hex(skey))

    @classmethod
    def create_feed(cls) -> Optional[Feed]:
        assert cls.feed_manager is not None, "call class first"
        key, _ = pure25519.create_keypair()
        skey = key.sk_s[:32]
        vkey = key.vk_s
        feed = cls.feed_manager.create_feed(vkey, skey)
        # self.save_keys()
        cls.save_config()
        return feed

    @classmethod
    def create_child_feed(cls, parent: Union[Feed, bytes]) -> Optional[Feed]:
        assert cls.feed_manager is not None, "call class first"
        key, _ = pure25519.create_keypair()
        skey = key.sk_s[:32]
        vkey = key.vk_s
        feed = cls.feed_manager.create_child_feed(parent, vkey, skey)
        # self.save_keys()
        cls.save_config()
        return feed

    @classmethod
    def create_contn_feed(cls, parent: Union[Feed, bytes]) -> Optional[Feed]:
        assert cls.feed_manager is not None, "call class first"
        key, _ = pure25519.create_keypair()
        skey = key.sk_s[:32]
        vkey = key.vk_s
        feed = cls.feed_manager.create_contn_feed(parent, vkey, skey)
        # self.save_keys()
        cls.save_config()
        return feed

    @classmethod
    def _send(cls, sock: socket.socket) -> None:
        # ask for missing packets
        global stop_threads
        while not stop_threads:
            msg = None
            cls.queue_lock.acquire()
            if len(cls.queue) > 0:
                msg = cls.queue[0]
                cls.queue = cls.queue[1:]
            cls.queue_lock.release()
            if msg is not None:
                # add reserved 8B
                msg = bytes(8) + msg
                sock.sendto(msg, cls.multicast_group)
            time.sleep(2)

    @classmethod
    def _listen(cls, sock: socket.socket, own: int) -> None:
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
            cls.chain_lock.acquire()
            try:
                fid = cls.chain_table[msg_hash]
                cls.chain_lock.release()
                cls._handle_blob(fid, msg, msg_hash)
                continue
            except Exception:
                cls.chain_lock.release()

            dmx = msg[:7]
            cls.dmx_lock.acquire()
            try:
                fn, fid = cls.dmx_table[dmx]
                cls.dmx_lock.release()
                # now give message to handler
                fn(fid, msg)
            except Exception:
                # dmx value not found
                cls.dmx_lock.release()

    @classmethod
    def _want_feeds(cls):
        assert cls.feed_manager is not None, "call class first"
        global stop_threads
        while not stop_threads:
            wants = []
            for feed in cls.feed_manager:
                if to_hex(feed.fid) not in cls.feed_manager.keys:
                    # not 'own' feed -> request next packet
                    wants.append(feed.get_want())

            # now append to queue
            cls.queue_lock.acquire()
            for want in wants:
                if want not in cls.queue:
                    cls.queue.append(want)
            cls.queue_lock.release()
            time.sleep(10)

    @classmethod
    def _user_cmds(cls) -> None:
        global stop_threads
        while not stop_threads:
            cmd = input()
            if cmd in ["q", "quit"]:
                stop_threads = True

    @classmethod
    def io(cls) -> None:
        # create sockets
        s_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s_sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        s_sock.bind(("", 0))
        # for now use port number to filter out own messages
        _, port = s_sock.getsockname()

        r_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        r_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        r_sock.bind(cls.multicast_group)
        r_sock.settimeout(3)
        mreq = struct.pack("=4sl",
                           socket.inet_aton("224.1.1.1"),
                           socket.INADDR_ANY)
        r_sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)

        t = Thread(target=cls._listen, args=(r_sock, port,))
        t.start()

        t2 = Thread(target=cls._send, args=(s_sock,))
        t2.start()

        # not ideal solution, but should suffice for poc
        t3 = Thread(target=cls._want_feeds)
        t3.start()

        # for handling user input
        t4 = Thread(target=cls._user_cmds)
        t4.start()
