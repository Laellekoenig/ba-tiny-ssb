import os
from ubinascii import hexlify
from tinyssb.feed import *

fid = os.urandom(32)
print(hexlify(fid).decode())
key = os.urandom(32)

f = create_feed(fid)
append_bytes(f, b"hello world", key)
print(get_payload(f, 1))

append_blob(f, b"hello" + bytes(100) + b"test" + bytes(100) + b"end12", key)
print(get_payload(f, 2))

print(to_string(f))
