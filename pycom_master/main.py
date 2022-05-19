import os
import _thread
from network import WLAN
from tinyssb.node import Node
from tinyssb.ssb_util import create_keypair


def init(node: Node) -> None:
    fm = node.feed_manager

    # create master feed
    sk, vk = create_keypair()
    master_feed = fm.create_feed(vk, skey=sk)
    assert master_feed is not None
    node.set_master_fid(master_feed.fid)

    # create node feed
    sk, vk = create_keypair()
    node_feed = fm.create_child_feed(master_feed, vk, sk)
    assert node_feed is not None

    # create update feed
    sk, vk = create_keypair()
    update_feed = fm.create_child_feed(master_feed, vk, sk)
    assert update_feed is not None

    # create version control feed
    sk, vk = create_keypair()
    vc_feed = fm.create_child_feed(update_feed, vk, sk)
    assert vc_feed is not None

    node.version_manager.set_update_feed(update_feed)
    print("setup finished")


pycom.rgbled(0x00FF00)

# configure wlan
wlan = WLAN()
wlan.init(mode=WLAN.AP, ssid="tinyssb", auth=(WLAN.WPA2, "helloworld"))

# start node
node = Node("master", enable_http=True, path="")
# init(node)
_thread.start_new_thread(node.io, ())
