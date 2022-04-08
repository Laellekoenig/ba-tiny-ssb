from packet import Packet
from packet import pkt_from_bytes
from packet import create_genesis_pkt
from packet import create_succ

feed_id = bytes(32)
payload = b"test" + bytes(44)
seq = (1).to_bytes(4, "big")

genesis = create_genesis_pkt(feed_id, payload)
msg2 = b"second" + bytes(42)
second = create_succ(genesis, msg2)

# check second
seq2 = (2).to_bytes(4, "big")
pkt_from_bytes(feed_id, seq2, genesis.mid, second.wire)
