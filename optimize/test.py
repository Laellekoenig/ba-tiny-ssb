import os
import sys
from tinyssb.packet import *
from tinyssb.feed import get_feed
from ubinascii import unhexlify

# chain test
fid = bytearray(os.urandom(32))
seq = bytearray((4).to_bytes(4, "big"))
prev_mid = bytearray(os.urandom(20))
content = bytearray(b"hello world, this is a tadala test. this message is longert than 28B")
key = bytearray(os.urandom(32))

pkt, blbs = create_chain(fid, seq, prev_mid, content, key)

print(pkt.wire[0].type)
print(pkt.wire[0].payload)
print(pkt.seq)
for blob in blbs:
    print(blob.payload)




sys.exit(0)

fid = bytearray(os.urandom(32))
key = os.urandom(32)
payload = bytearray(b"hello" + bytes(43))

p = create_genesis_pkt(fid, payload, key)
print("---")
print(p.wire[0].reserved)
print(p.wire[0].dmx)
print(p.wire[0].type)
print(p.wire[0].payload)
print(p.wire[0].signature)
print("---")
print(p.fid)
print(p.seq)
print(p.prev_mid)
print(p.mid)

str_fid = "059d53929536f131db45f83412e3bd9c96ffc5b02308c840de0ec9f759f854f1"
f = get_feed(unhexlify(str_fid.encode()))
print(f.front_seq)
