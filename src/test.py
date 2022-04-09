from packet import Packet
from packet import pkt_from_bytes
from packet import create_genesis_pkt
from packet import create_succ
from log import Log
from log_manager import LogManager
from ssb_util import to_hex

# PACKET TEST
# feed_id = bytes(32)
# payload = b"test" + bytes(44)
# seq = (1).to_bytes(4, "big")

# genesis = create_genesis_pkt(feed_id, payload)
# msg2 = b"second" + bytes(42)
# second = create_succ(genesis, msg2)

# # check second
# seq2 = (2).to_bytes(4, "big")
# pkt_from_bytes(feed_id, seq2, genesis.mid, second.wire)


# LOG TEST
# feed_id = os.urandom(32)
# log = create_new_log(feed_id, payload=b"hello 1")
# log.append_payload(b"hello 2")
# log.append_payload(b"hello 3")
# log.append_payload(b"hello 4")

# logs = get_logs_in_dir()
# log = logs[0]
# print(len(log._mids))
# print(log._mids)

# for entry in log:
#     print(entry.payload)

lm = LogManager()
print(len(lm))
