import os
import pycom
from network import WLAN
from tinyssb.node import Node
from tinyssb.ssb_util import create_keypair


# wifi setup
wifi = WLAN()
wifi.init(mode=WLAN.AP, ssid="tinyssb", auth=(WLAN.WPA2, "helloworld"))
pycom.rgbled(0x0000FF)


def init() -> None:
    n = Node("master")
    fm = n.feed_manager

    sk, vk = create_keypair()
    master = fm.create_feed(vk, sk)
    assert master is not None
    n.set_master_fid(bytes(master.fid))

    sk, vk = create_keypair()
    node_feed = fm.create_child_feed(master.fid, vk, sk)
    assert node_feed is not None

    sk, vk = create_keypair()
    update = fm.create_child_feed(master.fid, vk, sk)
    assert update is not None

    sk, vk = create_keypair()
    fm.create_child_feed(update.fid, vk, sk)

    n.version_manager.set_update_feed(update)
    del n


def clear() -> None:
    is_cfg = lambda x: x.endswith(".json")
    list_dir = os.listdir()
    files = list(filter(is_cfg, list_dir))

    for file in files:
        os.remove(file)

    if "_feeds" in list_dir:
        delete_dir("_feeds")
    if "_blobs" in list_dir:
        delete_dir("_blobs")


def delete_dir(path: str) -> None:
    files = os.listdir(path)
    subdirs = []

    for file in files:
        try:
            os.remove("{}/{}".format(path, file))
        except Exception:
            subdirs.append(file)

    for subdir in subdirs:
        delete_dir("{}/{}".format(path, subdir))

    os.rmdir(path)


def run() -> None:
    n = Node("master", enable_http=True)
    n.io()
