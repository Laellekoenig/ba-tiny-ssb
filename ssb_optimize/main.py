import sys
import os
import shutil
from tinyssb.node import Node
from tinyssb.ssb_util import create_keypair


def init() -> None:
    node = Node("master")
    fm = node.feed_manager
    skey, vkey = create_keypair()

    # main feed
    master_feed = fm.create_feed(vkey, skey)
    assert master_feed is not None
    master_fid = master_feed.fid
    del master_feed

    node.set_master_fid(bytes(master_fid))

    # node feed
    skey, vkey = create_keypair()
    _ = fm.create_child_feed(master_fid, vkey, skey)

    # update feed
    skey, vkey = create_keypair()
    update_feed = fm.create_child_feed(master_fid, vkey, skey)
    assert update_feed is not None
    update_fid = update_feed.fid

    # vc feed
    skey, vkey = create_keypair()
    _ = fm.create_child_feed(update_fid, vkey, skey)

    node.version_manager.set_update_feed(update_feed)


def clear() -> None:
    os.remove("feed_cfg.json")
    os.remove("node_cfg.json")
    os.remove("update_cfg.json")
    shutil.rmtree("_blobs")
    shutil.rmtree("_feeds")


def run() -> None:
    node = Node("master", enable_http=True)
    node.io()


if __name__ == "__main__":
    print("hello world 2")  
    if "i" in sys.argv:
        init()
    elif "c" in sys.argv:
        clear()
    elif "r" in sys.argv:
        run()
