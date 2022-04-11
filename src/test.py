from packet import Packet
from packet import pkt_from_bytes
from packet import create_genesis_pkt
from packet import create_succ
from log import Log
from log_manager import LogManager
from ssb_util import to_hex
from packet import make_chain
import os
from ssb_util import from_var_int
from ssb_util import to_var_int

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
# lm.create_new_log()
log = lm[0]

blob_msg = """Test Lorem ipsum dolor sit amet, consetetur sadipscing elitr, sed diam nonumy eirmod tempor invidunt ut labore et dolore magna aliquyam erat, sed diam voluptua. At vero eos et accusam et justo duo dolores et ea rebum. Stet clita kasd gubergren, no sea takimata sanctus est Lorem ipsum dolor sit amet. Lorem ipsum dolor sit amet, consetetur sadipscing elitr, sed diam nonumy eirmod tempor invidunt ut labore et dolore magna aliquyam erat, sed diam voluptua. At vero eos et accusam et justo duo dolores et ea rebum. Stet clita kasd gubergren, no sea takimata sanctus est Lorem ipsum dolor sit amet. Lorem ipsum dolor sit amet, consetetur sadipscing elitr, sed diam nonumy eirmod tempor invidunt ut labore et dolore magna aliquyam erat, sed diam voluptua. At vero eos et accusam et justo duo dolores et ea rebum. Stet clita kasd gubergren, no sea takimata sanctus est Lorem ipsum dolor sit amet.   

Duis autem vel eum iriure dolor in hendrerit in vulputate velit esse molestie consequat, vel illum dolore eu feugiat nulla facilisis at vero eros et accumsan et iusto odio dignissim qui blandit praesent luptatum zzril delenit augue duis dolore te feugait nulla facilisi. Lorem ipsum dolor sit amet,"""

# print(len(log))
# print(pkt.pkt_type)

fid = lm[0].feed_id
child = lm.create_child_log(fid)
print(child)
