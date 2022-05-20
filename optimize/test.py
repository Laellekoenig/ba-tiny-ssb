import os
from ubinascii import hexlify
from tinyssb.feed import *

fid1 = os.urandom(32)
key1 = os.urandom(32)

fid2 = os.urandom(32)
key2 = os.urandom(32)

f1 = create_feed(fid1)
f2 = create_contn_feed(f1, key1, fid2, key2)

w = get_wire(f1, 1)
print(w[16:48] == f2.fid)
print(get_prev(f2) == f1.fid)
print(get_contn(f1) == f2.fid)
