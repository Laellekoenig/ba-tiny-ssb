import sys
import os
import shutil
from poc.node import Node
import pure25519
from typing import Tuple


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
    nodes = [master, node_a, node_b, node_c]

    # create code folders
    for node in nodes:
        if "code" not in os.listdir(node.path):
            os.mkdir(node.path + "/code")

            # now copy code files
            code_path = "update_code"
            for f in os.listdir(code_path):
                shutil.copy(code_path + "/" + f, node.path + "/code")

    # create meta feed on master, add root to every other node -> subscribe
    main_feed = master.create_feed()
    assert main_feed is not None, "failed to create feed"
    meta_path = "data/master/_feeds"
    meta_path += "/" + os.listdir(meta_path)[0]

    for node in nodes[1:]:
        shutil.copy(meta_path, node.path + "/_feeds")

    # TODO: remove this testing part
    # add first message for testing purposes to master feed
    main_feed.append_blob(b"Hello World!")
    # create child feed
    child_feed = master.create_child_feed(main_feed)
    assert child_feed is not None, "failed to create child feed"
    child_feed.append_blob(b"Second feed.")
    child_feed.append_blob(b"End second feed.")

    main_feed.append_blob(b"End main feed.")

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
