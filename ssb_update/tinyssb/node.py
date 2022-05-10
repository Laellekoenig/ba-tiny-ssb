import _thread
import json
import os
import socket
import struct
import sys
import time
from .feed_manager import FeedManager
from .html import HTMLVisualizer
from .ssb_util import to_hex
from .version_manager import VersionManager
from .version_util import string_version_graph
from hashlib import sha256


# non-micropython import
if sys.implementation.name != "micropython":
    # Optional type annotations are ignored in micropython
    from typing import Union


class Node:
    """
    A very basic client for the tinyssb network.
    Uses UDP multicast to communicate with other nodes.
    The sending queue is very naïve.
    """

    parent_dir = "data"
    multicast_group = ("224.1.1.1", 5000)
    cfg_file_name = "node_cfg.json"

    def __init__(self, name: str, enable_http: bool = False) -> None:
        self.name = name
        self.path = self.parent_dir + "/" + name
        # setup directories
        self._create_dirs()
        # create feed and version managers
        self.feed_manager = FeedManager(self.path)
        self.version_manager = VersionManager(self.path + "/code", self.feed_manager)
        self.master_fid = None
        # load configuration
        self._load_config()

        # support threading
        self.queue = []
        self.queue_lock = _thread.allocate_lock()

        self.html = None
        if self.master_fid is not None and enable_http:
            self.html = HTMLVisualizer(
                self.master_fid, self.feed_manager, self.version_manager
            )

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

    def _load_config(self) -> None:
        """
        Loads the contents of the self.cfg_file_name file into this instance of Node.
        The config contains the FIDs with associated keys and the FID of the master feed.
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

    def set_master_fid(self, fid: Union[bytes, str]) -> None:
        """
        Used for manually setting this node's master feed.
        The provided FID may be a hex string or bytes.
        """
        if type(fid) is bytes:
            fid = to_hex(fid)
        self.master_fid = fid
        self.save_config()

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
        assert update_feed is not None, "failed to get feed"

        # configure and start version manager
        self.version_manager.set_update_feed(update_feed)
        return True

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

            time.sleep(0.2)  # add some delay

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

            # packet or request
            dmx = msg[:7]
            tpl = self.feed_manager.consult_dmx(dmx)
            if tpl is not None:
                (fn, fid) = tpl  # unpack
                requested_wire = fn(fid, msg)

                if requested_wire is not None:
                    # request -> add packet to queue
                    self.queue_lock.acquire()
                    self.queue.append(requested_wire)
                    self.queue_lock.release()

                # check if version control already running (in case update feed has arrived)
                if not self.version_manager.is_configured():
                    self._start_version_control()

    def _want_feeds(self):
        """
        Infinite loop that adds "wants" to the queue -> Asks for new feed entries.
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

    def _user_input(self):
        while True:
            inpt = input()

            # handle different commands
            if inpt in ["p", "print"]:
                print(self.feed_manager)

            if inpt in ["e", "emergency"]:
                file_name = "test.txt"
                update = "emergency"
                depends_on = int(input("depends on: "))
                self.version_manager.emergency_update_file(
                    file_name, update, depends_on
                )

            if inpt in ["a", "apply"]:
                # file_name = input("file name: ")
                file_name = "test.txt"
                seq = int(input("sequence number: "))
                self.version_manager.add_apply(file_name, seq)

            if inpt in ["sudo"]:
                cmd = input("cmd: ")
                exec(cmd)

            if inpt in ["u", "update"]:
                file_name = "test.txt"
                update = input("update: ")
                dep = int(input("depends on: "))
                self.version_manager.update_file(file_name, update, dep)

            if inpt in ["t", "tree"]:
                assert self.version_manager.vc_feed is not None
                file_name = "test.txt"
                file_fid, _ = self.version_manager.vc_dict[file_name]
                file_feed = self.feed_manager.get_feed(file_fid)
                assert file_feed is not None, "failed to get feed"
                apply = self.version_manager.vc_feed.get_newest_apply(file_fid)
                print(string_version_graph(file_feed, self.feed_manager, apply))

            if inpt in ["l", "large"]:
                # large update
                file_name = "test.txt"

                # read 'large' file (1MB)
                f = open("large_update/data.csv")
                update = f.read()
                f.close()

                # add update
                dep = int(input("depends on: "))
                self.version_manager.update_file(file_name, update, dep)

    def _hhtp_server(self, server_socket: socket.socket) -> None:
        while True:
            client_sock, _ = server_socket.accept()
            _thread.start_new_thread(self._handle_http, (client_sock,))

    def _handle_http(self, client_sock: socket.socket) -> None:
        assert self.html is not None, "no HTMLVisualizer initialized"
        msg = client_sock.recv(4096)

        if len(msg) == 0:
            client_sock.close()
            return

        # get request
        request = msg.decode("utf-8").split("\n")
        if len(request) == 0:
            client_sock.close()
            return

        if "POST" in request[0]:
            # update received
            self._handle_http_update(request[0], client_sock, request[-1])
            client_sock.close()
            return

        get = request[0]
        if "GET" not in get:
            client_sock.close()
            return

        # extract command
        cmd = get.split(" ")[1]

        page = None

        # handle depending on cmd
        if cmd in ["/", "/feed_status"]:
            page = self.html.get_main_menu()

        if cmd == "/version_status":
            page = self.html.get_version_status()

        if cmd == "/file_browser":
            page = self.html.get_file_browser()

        if cmd.startswith("/get_file_version"):
            file_name = cmd[len("/get_file_version_"):]
            page = self.html.get_file(file_name, version=True)

        elif cmd.startswith("/get_file"):
            file_name = cmd[len("/get_file_"):]
            page = self.html.get_file(file_name)

        if cmd == "/create_new_file":
            page = self.html.get_create_new_file()

        if cmd.startswith("/new_file_"):
            # reformat file name
            file_name = cmd[len("/new_file_"):]
            dot_index= file_name.rfind("_")
            file_name = file_name[:dot_index] + "." + file_name[dot_index + 1:]

            # create new file
            self.version_manager.create_new_file(file_name)

            # serve page
            page = self.html.get_new_file()

        if cmd.startswith("/apply"):
            cmd = cmd[len("/apply_"):]  # cut off prefix

            # get version number and file name
            split = cmd.split("_")
            v = int(split[-1])
            file_name = "_".join(split[:-2]) + "." + split[-2]

            # apply update
            self.version_manager.add_apply(file_name, v)

            # serve page
            page = self.html.get_version_status()

        if cmd.startswith("/edit"):
            cmd = cmd[len("/edit_"):]
            split = cmd.split("_")
            v = int(split[-1])
            file_name = "_".join(split[:-2]) + "." + split[-2]
            page = self.html.get_edit_file(file_name, v)

        if page is None:
            page = self.html.get_404()

        # send requested content
        to_response = lambda x: "HTTP/1.0 200 OK\n\n{}".format(x).encode()
        client_sock.sendall(to_response(page))
        client_sock.close()

    def _handle_http_update(self, post: str, client_sock: socket.socket, request: str) -> None:
        assert self.html is not None
        emergency = "emergency_update" in post

        if emergency:
            post = post[len("POST /emergency_update_"):]
        else:
            post = post[len("POST /update_"):]

        cmd = post.split(" ")[0]
        split = cmd.split("_")
        v_num = int(split[-1])
        file_name = "_".join(split[:-2])+ "." + split[-2]

        # json -> string
        code = repr(request[1:-1])[1:-1]  # cut off "" and ''
        code = code.replace("\\\\n", "\n")
        code = code.replace("\\\\t", "\t")

        # add update
        if emergency:
            self.version_manager.emergency_update_file(file_name, code, v_num)
        else:
            self.version_manager.update_file(file_name, code, v_num)

        # send response
        client_sock.sendall(b"ok")

    def io(self) -> None:
        """
        Starts one listening and one sending threads.
        """
        # sending socket
        s_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s_sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        s_sock.bind(("", 0))
        # use port number to filter out own messages
        _, port = s_sock.getsockname()

        # receiving socket
        r_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        r_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        r_sock.bind(self.multicast_group)
        r_sock.settimeout(3)
        mreq = struct.pack("=4sl", socket.inet_aton("224.1.1.1"), socket.INADDR_ANY)
        r_sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)

        _thread.start_new_thread(
            self._listen,
            (
                r_sock,
                port,
            ),
        )
        _thread.start_new_thread(self._send, (s_sock,))
        _thread.start_new_thread(self._user_input, ())

        # start http server if enabled
        if self.html is not None:
            # http socket
            server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server_sock.bind(("0.0.0.0", 8000))
            server_sock.listen(1)
            _thread.start_new_thread(self._hhtp_server, (server_sock,))

        # keep main thread alive
        self._want_feeds()
