import os
from ubinascii import hexlify
from tinyssb.feed import *
from tinyssb.feed_manager import FeedManager

fid1 = os.urandom(32)
key1 = os.urandom(32)

fid2 = os.urandom(32)
key2 = os.urandom(32)

fid3 = os.urandom(32)
key3 = os.urandom(32)

keys = {
    fid1: key1,
    fid2: key2,
    fid3: key3,
}

f1 = create_feed(fid1)
f2 = create_contn_feed(f1, key1, fid2, key2)
f3 = create_child_feed(f1, key1, fid3, key3)

w = get_wire(f1, 1)

fm = FeedManager()
fm.update_keys(keys)
print(fm)

print(fm.keys)

#--------------------------------- clean up ------------------------------------
for file in listdir("_feeds"):
    if file.endswith(".log") or file.endswith(".head"):
        os.remove("_feeds/{}".format(file))

for file in listdir("_blobs"):
    if file.startswith("."):
        continue
    os.remove("_blobs{}".format(file))

for file in listdir():
    if file.endswith(".json"):
        os.remove(file)
