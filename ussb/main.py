from ussb.feed import create_feed, create_child_feed
from ussb.feed_manager import FeedManager
from ussb.node import Node
from ussb.util import listdir
import os
import sys


def init() -> None:
    fm = FeedManager()
    mkey, mfid = fm.generate_keypair()
    master_feed = create_feed(mfid)

    ckey, cfid = fm.generate_keypair()
    _ = create_child_feed(master_feed, mkey, cfid, ckey)

    ukey, ufid = fm.generate_keypair()
    update_feed = create_child_feed(master_feed, mkey, ufid, ukey)

    vkey, vfid = fm.generate_keypair()
    _ = create_child_feed(update_feed, ukey, vfid, vkey)

    n = Node()
    n.set_master_feed(master_feed)


def clean() -> None:
    if "_feeds" in listdir():
        for file in listdir("_feeds"):
            if file.endswith(".log") or file.endswith(".head"):
                os.remove("_feeds/{}".format(file))
        os.rmdir("_feeds")

    if "_blobs" in listdir():
        for file in listdir("_blobs"):
            if file.startswith("."):
                continue
            for file2 in listdir("_blobs/{}".format(file)):
                if file2.startswith("."):
                    continue
                os.remove("_blobs/{}/{}".format(file, file2))

            os.rmdir("_blobs/{}".format(file))
        os.rmdir("_blobs")

    for file in listdir():
        if file.endswith(".json"):
            os.remove(file)


def main() -> int:
    if "c" in sys.argv:
        clean()
        return 0
    if "i" in sys.argv:
        init()
        return 0
    if "rr" in sys.argv:
        clean()
        init()
        n = Node()
        n.io()
    if "r" in sys.argv:
        n = Node(enable_http=True)
        n.io()

    return 1


if __name__ == "__main__":
    sys.exit(main())
