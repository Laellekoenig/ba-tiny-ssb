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
    # master
    master = Node("master")
    master_path = master.path

    # create meta feed on master, add root to every other node -> subscribe
    sk, vk = get_keypair()
    master_feed = master.feed_manager.create_feed(vk, skey=sk)
    assert master_feed is not None, "failed to create feed"
    master.set_master_fid(master_feed.fid)
    meta_path = "data/master/_feeds"
    meta_path += "/" + os.listdir(meta_path)[0]

    # create nodes
    paths = []

    # node a
    a = Node("a")
    a.set_master_fid(master_feed.fid)
    paths.append(a.path)
    del a

    # node b
    b = Node("b")
    b.set_master_fid(master_feed.fid)
    paths.append(b.path)
    del b

    # node c
    c = Node("c")
    c.set_master_fid(master_feed.fid)
    paths.append(c.path)
    del c

    # create code folders
    for path in paths + [master_path]:
        # copy code files
        code_path = "update_code"
        for f in os.listdir(code_path):
            shutil.copy(code_path + "/" + f, path + "/code")

    for path in paths:
        shutil.copy(meta_path, path + "/_feeds")

    # add things to master feed
    sk, vk = get_keypair()
    node_feed = master.feed_manager.create_child_feed(master_feed, vk, sk)
    assert node_feed is not None, "failed to create node feed"
    # inserting node feeds not necessary for this poc

    # create update feed
    sk, vk = get_keypair()
    update_feed = master.feed_manager.create_child_feed(master_feed, vk, sk)
    assert update_feed is not None, "failed to create update feed"

    # create version control feed
    sk, vk = get_keypair()
    vc_feed = master.feed_manager.create_child_feed(update_feed, vk, sk)
    assert vc_feed is not None, "failed to create vc feed"

    update = """import os

def example() -> None:
    print("Hello World!")


def main() -> int:
    print("testing update")
    example()
    return 1

if __name__ == "__main__":
    main()
    """
    # test update
    master.version_manager.set_update_feed(update_feed)
    master.version_manager.update_file("example1.py", update)

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
