from ussb.feed import create_feed, create_child_feed
from ussb.feed_manager import FeedManager
from ussb.node import Node
from ussb.util import listdir, PYCOM
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


def init_and_export() -> None:
    fm = FeedManager()
    mkey, mfid = fm.generate_keypair()
    master_feed = create_feed(mfid)

    os.mkdir("ROOT_EXPORT")
    os.mkdir("ROOT_EXPORT/_feeds")
    for file in listdir("_feeds"):
        if file.endswith(".head") or file.endswith(".log"):
            f = open("_feeds/{}".format(file), "rb")
            content = f.read()
            f.close()

            f = open("ROOT_EXPORT/_feeds/{}".format(file), "wb")
            f.write(content)
            f.close()
            del content

    ckey, cfid = fm.generate_keypair()
    _ = create_child_feed(master_feed, mkey, cfid, ckey)

    ukey, ufid = fm.generate_keypair()
    update_feed = create_child_feed(master_feed, mkey, ufid, ukey)

    vkey, vfid = fm.generate_keypair()
    _ = create_child_feed(update_feed, ukey, vfid, vkey)

    n = Node()
    n.set_master_feed(master_feed)

    f = open("node_cfg.json")
    content = f.read()
    f.close()

    f = open("ROOT_EXPORT/node_cfg.json", "w")
    f.write(content)
    f.close()


def clean() -> None:
    if "_feeds" in listdir():
        for file in listdir("_feeds"):
            if file.endswith(".log") or file.endswith(".head"):
                os.remove("_feeds/{}".format(file))
        os.rmdir("_feeds")

    for file in listdir():
        if file.endswith(".json"):
            os.remove(file)

    if "ROOT_EXPORT" in listdir():
        for file in listdir("ROOT_EXPORT/_feeds"):
            if file.startswith("."):
                continue
            os.remove("ROOT_EXPORT/_feeds/{}".format(file))
        os.rmdir("ROOT_EXPORT/_feeds")
        os.remove("ROOT_EXPORT/node_cfg.json")
        os.rmdir("ROOT_EXPORT")

    # FIXME
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


if PYCOM:
    import pycom
    from network import LoRa, WLAN

    # lora setup
    lora = LoRa(
        mode=LoRa.LORA,
        region=LoRa.EU868,
        tx_power=20,
        power_mode=LoRa.ALWAYS_ON,
    )

    lora.sf(7)
    lora.bandwidth(LoRa.BW_250KHZ)
    lora.coding_rate(LoRa.CODING_4_5)

    def run_http() -> None:
        # wifi setup
        wifi = WLAN()
        ssid = "ussb_0"
        while wifi.scan(ssid=ssid):
            ssid = ssid.split("_")[0] + "_" + str(int(ssid.split("_")[1]) + 1)

        wifi.init(mode=WLAN.AP, ssid=ssid, auth=(WLAN.WPA2, "helloworld"))
        pycom.heartbeat(False)
        pycom.rgbled(0x00FF00)
        n = Node(enable_http=True)
        n.io()

    def run() -> None:
        pycom.heartbeat(False)
        pycom.rgbled(0x0000FF)
        n = Node()
        n.io()

    run_http()

else:

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
            n = Node()
            n.io()
        if "w" in sys.argv:
            n = Node(enable_http=True)
            n.io()
        if "e" in sys.argv:
            init_and_export()
            return 0
        return 1

    if __name__ == "__main__":
        sys.exit(main())
