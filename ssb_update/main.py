import os
import pure25519
import shutil
import sys
from tinyssb.node import Node
from tinyssb.ssb_util import is_dir
from typing import Tuple


def get_keypair() -> Tuple[bytes, bytes]:
    """
    Creates an elliptic curve key pair and returns it as a tuple.
    """
    keys, _ = pure25519.create_keypair()
    skey = keys.sk_s[:32]
    vkey = keys.vk_s
    return (skey, vkey)


def init() -> None:
    """
    Initializes all of the directories and files for the proof-of-concept.
    """
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
        # shutil.rmtree(path + "/code")
        # shutil.copytree(code_path, path + "/code")
        # shutil.copy(code_path, path)
        for f in os.listdir(code_path):
            if is_dir(code_path + "/" + f):
                shutil.copytree(code_path + "/" + f, path + "/" + f)
            else:
                shutil.copy(code_path + "/" + f, path)
        # for f in os.listdir(code_path):
            # shutil.copy(code_path + "/" + f, path + "/code")

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

    # test update
    master.version_manager.set_update_feed(update_feed)
    master.version_manager.update_file("test.txt", "up1", depends_on=0)
    master.version_manager.update_file("test.txt", "up1\nup2", depends_on=1)
    master.version_manager.update_file("test.txt", "up1\nup2\nup3", depends_on=2)
    master.version_manager.update_file("test.txt", "up1\nup4", depends_on=1)
    master.version_manager.update_file("test.txt", "up1\nup4\nup5", depends_on=4)

    # ready
    return


def master() -> None:
    master = Node("master", enable_http=True)
    master.io()


def node(name: str) -> None:
    node = Node(name)
    node.io()


def clean() -> None:
    shutil.rmtree("data")


if __name__ == "__main__":
    """
    Proof-of-concept can be started with different arguments:
    i/init -> creates all of the needed directories and files
    c/clear -> deletes all of the created directories and files
    m/master -> starts the master node (may append updates)
    n/node name -> starts a node with the given name (a, b or c)
    """
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

        if "mm" in sys.argv:
            clean()
            init()
            master()
