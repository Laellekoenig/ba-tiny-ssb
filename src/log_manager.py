import os
from log import Log
from packet import create_genesis_pkt
from ssb_util import is_file
from ssb_util import to_hex
from ssb_util import from_hex


class LogManager:

    def __init__(self, path: str = ""):
        self.path = path
        self.log_dir = self.path + "_logs"
        self.blob_dir = self.path + "_blobs"
        self._check_dirs()
        self.logs = self._get_logs()

    def __len__(self):
        return len(self.logs)

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
            print(log.feed_id)
            print(feed_id)
            if log.feed_id == feed_id:
                return log

        return None

    def create_new_log(self,
                       feed_id: bytes = None,
                       payload: bytes = bytes(48),
                       trusted_seq: int = 0,
                       trusted_mid: bytes = None,
                       parent_seq: int = 0,
                       parent_fid: bytes = bytes(32)) -> str:
        """creates new Log instance and adds it to 'logs' list
        the feed_id of the log is returned as a string"""

        if feed_id is None:
            feed_id = os.urandom(32)

        if trusted_mid is None:
            # tinyssb convention, self-signed
            trusted_mid = feed_id[:20]

        trusted_seq = trusted_seq.to_bytes(4, "big")
        parent_seq = parent_seq.to_bytes(4, "big")

        assert len(feed_id) == 32, "feed_id must be 32B"
        assert len(payload) <= 48, "payload may not be longer than 48B"
        assert len(trusted_seq) == 4, "trusted seq must be 4B"
        assert len(trusted_mid) == 20, "trusted mid must be 20B"
        assert len(parent_seq) == 4, "parent seq must be 4B"
        assert len(parent_fid) == 32, "parent_fid must be 32B"

        pkt = create_genesis_pkt(feed_id, payload)

        # create log file
        file_name = self.log_dir + "/" + to_hex(feed_id) + ".log"
        if os.path.isfile(file_name):
            return None

        header = bytes(12) + feed_id + parent_fid + parent_seq
        header += trusted_seq + trusted_mid
        header += pkt.seq + pkt.mid

        assert len(header) == 128, f"header must be 128B, was {len(header)}"

        # create new log file
        with open(file_name, "wb") as f:
            f.write(header)
            f.write(bytes(8))  # reserved 8B at start of entry
            f.write(pkt.wire)

        log = Log(file_name)
        self.logs.append(log)
        return to_hex(log.feed_id)
