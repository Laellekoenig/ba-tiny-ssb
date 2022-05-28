from network import WLAN
from ussb.feed import create_feed, create_child_feed
from ussb.feed_manager import FeedManager
from ussb.node import Node
from ussb.util import listdir
import os
import pycom


wifi = WLAN()
wifi.init(mode=WLAN.AP, ssid="ussb", auth=(WLAN.WPA2, "helloworld"))
pycom.rgbled(0x00FF00)


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

    for file in listdir():
        if file.endswith(".json"):
            os.remove(file)

    if "_blobs" in listdir():
        for file in listdir("_blobs"):
            for file2 in listdir("_blobs/{}".format(file)):
                os.remove("_blobs/{}/{}".format(file, file2))
            os.rmdir("_blobs/{}".format(file))
        os.rmdir("_blobs")


def run() -> None:
    n = Node(enable_http=True)
    n.io()
