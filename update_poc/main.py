import sys
import os
import shutil
from poc.node import Node
import pure25519
from typing import Tuple
import json
from tinyssb.ssb_util import to_hex


def get_keypair() -> Tuple[bytes, bytes]:
    keys, _ = pure25519.create_keypair()
    skey = keys.sk_s[:32]
    vkey = keys.vk_s
    return (skey, vkey)


def init() -> None:
    # create nodes
    master = Node("master")
    node_a = Node("a")
    node_b = Node("b")
    node_c = Node("c")
    nodes = [node_a, node_b, node_c]

    # create code folders
    for node in nodes + [master]:
        # copy code files
        code_path = "update_code"
        for f in os.listdir(code_path):
            shutil.copy(code_path + "/" + f, node.path + "/code")

    # create meta feed on master, add root to every other node -> subscribe
    master_feed = master.create_feed()
    assert master_feed is not None, "failed to create feed"
    meta_path = "data/master/_feeds"
    meta_path += "/" + os.listdir(meta_path)[0]

    for node in nodes:
        shutil.copy(meta_path, node.path + "/_feeds")


    # set master fid for all nodes
    for node in nodes + [master]:
        node.set_master_fid(master_feed.fid)

    # blob test
    master_feed.append_bytes(b"first msg")
    master_feed.append_blob(b"short blob")
    master_feed.append_blob(b"long blob" + bytes(400) + b"end")
    master_feed.append_bytes(b"end of test")

    # node_feed = master.create_child_feed(master_feed)
    # assert node_feed is not None, "failed to create node feed"
    # rest is not necessary for this poc

    # create update feed
    # update_feed = master.create_child_feed(master_feed)
    # assert update_feed is not None, "failed to create update feed"

    # ready
    return


def master() -> None:
    master = Node("master")
    master.io()


def node(name: str) -> None:
    node = Node(name)
    node.io()


def clean() -> None:
    shutil.rmtree("data")


if __name__ == "__main__":
    if len(sys.argv) == 3 and ("node" in sys.argv or "n" in sys.argv):
        name = sys.argv[-1]
        node(name)
    else:
        if "init" in sys.argv or "i" in sys.argv:
            init()

        if "master" in sys.argv or "m" in sys.argv:
            master()

        if "clean" in sys.argv or "c" in sys.argv:
            clean()
