import os
from log import Log
from packet import create_genesis_pkt
from packet import create_child_pkt
from ssb_util import is_file
from ssb_util import to_hex
from ssb_util import from_hex
from packet import PacketType
from packet import create_parent_pkt


class LogManager:

    def __init__(self, path: str = ""):
        self.path = path
        self.log_dir = self.path + "_logs"
        self.blob_dir = self.path + "_blobs"
        self._check_dirs()
        self.logs = self._get_logs()

    def __len__(self):
        return len(self.logs)

    def __getitem__(self, i: int) -> Log:
        return self.logs[i]

    def _check_dirs(self):
        """checks if the log and blob dirs already exists
        if not, new ones are created"""
        if not is_file(self.log_dir):
            os.mkdir(self.log_dir)
        if not is_file(self.blob_dir):
            os.mkdir(self.blob_dir)

    def _get_logs(self) -> [Log]:
        """reads all the log files that are in self.log_dir
        and returns list of all Log instances"""
        logs = []
        files = os.listdir(self.log_dir)
        for f in files:
            if f.endswith(".log"):
                logs.append(Log(self.log_dir + "/" + f))

        return logs

    def get_log(self, feed_id: bytes) -> Log:
        """searches for specific log in self.logs
        expects feed_id as bytes as input
        also handles string representation and file name"""

        # transform to bytes
        if type(feed_id) is str:
            if feed_id.endswith(".log"):
                feed_id = feed_id[:-4]
            feed_id = from_hex(feed_id)

        # search
        for log in self.logs:
            if log.feed_id == feed_id:
                return log

        return None

    def create_new_log(self,
                       feed_id: bytes = None,
                       trusted_seq: int = 0,
                       trusted_mid: bytes = None,
                       payload: bytes = bytes(48),
                       pkt_type: PacketType = PacketType.plain48,
                       parent_fid: bytes = bytes(32),
                       parent_seq: int = 0) -> str:
        """creates new log instance and adds it to 'logs' list
        the feed_id of the log is returned as a string"""

        if feed_id is None:
            feed_id = os.urandom(32)

        if trusted_mid is None:
            # tinyssb convention, self-signed
            trusted_mid = feed_id[:20]

        trusted_seq = trusted_seq.to_bytes(4, "big")
        parent_seq = parent_seq.to_bytes(4, "big")

        assert len(feed_id) == 32, "feed_id must be 32b"
        assert len(payload) <= 48, "payload may not be longer than 48b"
        assert len(trusted_seq) == 4, "trusted seq must be 4b"
        assert len(trusted_mid) == 20, "trusted mid must be 20b"
        assert len(parent_seq) == 4, "parent seq must be 4b"
        assert len(parent_fid) == 32, "parent_fid must be 32b"

        if pkt_type == PacketType.plain48:
            pkt = create_genesis_pkt(feed_id, payload)
        if pkt_type == PacketType.ischild:
            pkt = create_child_pkt(feed_id, payload)

        # create log file
        file_name = self.log_dir + "/" + to_hex(feed_id) + ".log"
        if os.path.isfile(file_name):
            return None

        header = bytes(12) + feed_id + parent_fid + parent_seq
        header += trusted_seq + trusted_mid
        header += pkt.seq + pkt.mid

        assert len(header) == 128, f"header must be 128b, was {len(header)}"

        # create new log file
        with open(file_name, "wb") as f:
            f.write(header)
            f.write(bytes(8))  # reserved 8b at start of entry
            f.write(pkt.wire)

        log = Log(file_name)
        self.logs.append(log)
        return to_hex(log.feed_id)

    def create_child_log(self, parent_fid: bytes,
                         child_fid: bytes = None) -> str:
        """starts a child log for the given feed id
        returns the feed id of the newly created child log"""

        parent = self.get_log(parent_fid)
        if parent is None:
            return None

        if child_fid is None:
            child_fid = os.urandom(32)

        # add child info to parent
        parent_seq = (parent.front_seq + 1).to_bytes(4, "big")
        parent_pkt = create_parent_pkt(parent.feed_id, parent_seq,
                                       parent.front_mid, child_fid)
        parent.append_pkt(parent_pkt)

        # create child log
        child_payload = parent_pkt.feed_id + parent_pkt.seq
        child_payload += parent_pkt.wire[-12:]
        return self.create_new_log(child_fid,
                                   payload=child_payload,
                                   pkt_type=PacketType.ischild,
                                   parent_fid=parent.feed_id,
                                   parent_seq=parent.front_seq)
