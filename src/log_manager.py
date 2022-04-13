import os
from log import Log
from packet import create_child_pkt
from packet import create_contn_pkt
from packet import create_end_pkt
from packet import create_parent_pkt
from ssb_util import from_hex
from ssb_util import is_file
from ssb_util import to_hex


class LogManager:
    """
    Manages and creates Log instances.
    The path can be specified in the constructor with path="path"
    (TODO: test).
    """

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
        """
        Checks whether the _log and _blob firectories already exist.
        If not, new directories are created.
        """
        if not is_file(self.log_dir):
            os.mkdir(self.log_dir)
        if not is_file(self.blob_dir):
            os.mkdir(self.blob_dir)

    def _get_logs(self) -> [Log]:
        """
        Reads all .log files in the self.log_dir directory.
        Returns a list of all Log instances.
        """
        logs = []
        files = os.listdir(self.log_dir)
        for f in files:
            if f.endswith(".log"):
                logs.append(Log(self.log_dir + "/" + f))

        return logs

    def get_log(self, fid: bytes) -> Log:
        """
        Searches for a specific Log in self.logs.
        The feed ID can be handed in as bytes, a hex string
        or a file name.
        Retruns 'None' if the log cannot be found.
        """
        # transform to bytes
        if type(fid) is str:
            if fid.endswith(".log"):
                fid = fid[:-4]
            fid = from_hex(fid)

        # search
        for log in self.logs:
            if log.fid == fid:
                return log

        return None

    def create_new_log(self,
                       fid: bytes = None,
                       trusted_seq: int = 0,
                       trusted_mid: bytes = None,
                       parent_seq: int = 0,
                       parent_fid: bytes = bytes(32)) -> Log:
        """
        Creates a new Log instance and adds it to self.logs.
        The feed ID, trusted sequence number, trusted message ID,
        parent feed ID and parent sequence number can be explicitly
        specified.
        If no feed ID is specified, a random one is generated.
        Returns the newly created Log instance.
        """
        if fid is None:
            fid = os.urandom(32)

        if trusted_mid is None:
            trusted_mid = fid[:20]  # tinyssb convention, self-signed

        trusted_seq = trusted_seq.to_bytes(4, "big")
        parent_seq = parent_seq.to_bytes(4, "big")

        assert len(fid) == 32, "fid must be 32b"
        assert len(trusted_seq) == 4, "trusted seq must be 4b"
        assert len(trusted_mid) == 20, "trusted mid must be 20b"
        assert len(parent_seq) == 4, "parent seq must be 4b"
        assert len(parent_fid) == 32, "parent_fid must be 32b"

        # create log file
        file_name = self.log_dir + "/" + to_hex(fid) + ".log"
        if os.path.isfile(file_name):
            return None

        header = bytes(12) + fid + parent_fid + parent_seq
        header += trusted_seq + trusted_mid
        header += trusted_seq + fid[:20]  # self-signed

        assert len(header) == 128, f"header must be 128b, was {len(header)}"

        # create new log file
        with open(file_name, "wb") as f:
            f.write(header)

        log = Log(file_name)
        self.logs.append(log)
        return log

    def create_child_log(self, parent_fid: bytes,
                         child_fid: bytes = None) -> Log:
        """
        Creates and returns a new child Log instance for the given parent.
        The parent can be passed either as a Log instance, feed ID bytes,
        feed ID hex string or file name.
        The child feed ID can be explicitly definied.
        """
        if type(parent_fid) is Log:
            parent = parent_fid
        else:
            parent = self.get_log(parent_fid)

        if parent is None:
            return None

        if child_fid is None:
            child_fid = os.urandom(32)

        # add child info to parent
        parent_seq = (parent.front_seq + 1).to_bytes(4, "big")
        parent_pkt = create_parent_pkt(parent.fid, parent_seq,
                                       parent.front_mid, child_fid)
        parent.append_pkt(parent_pkt)

        # create child log
        child_payload = parent_pkt.fid + parent_pkt.seq
        child_payload += parent_pkt.wire[-12:]
        child_log = self.create_new_log(child_fid,
                                        parent_fid=parent.fid,
                                        parent_seq=parent.front_seq)

        child_pkt = create_child_pkt(child_log.fid, child_payload)
        child_log.append_pkt(child_pkt)
        return child_log

    def create_contn_log(self, end_fid: bytes,
                         contn_fid: bytes = None) -> Log:
        """
        Ends the given log and returns a new continuation Log instance.
        The ending log can be passed either as a Log instance, feed ID bytes,
        feed ID hex string or file name.
        The continuation feed ID can be explicitly defined.
        """
        if type(end_fid) is Log:
            ending_log = end_fid
        else:
            ending_log = self.get_log(end_fid)

        if ending_log is None:
            return None

        if contn_fid is None:
            contn_fid = os.urandom(32)

        end_seq = (ending_log.front_seq + 1).to_bytes(4, "big")
        end_pkt = create_end_pkt(ending_log.fid, end_seq,
                                 ending_log.front_mid, contn_fid)

        ending_log.append_pkt(end_pkt)
        # create continuing log
        contn_payload = end_pkt.fid + end_pkt.seq
        contn_payload += end_pkt.wire[-12:]
        contn_log = self.create_new_log(contn_fid,
                                        parent_fid=ending_log.fid,
                                        parent_seq=ending_log.front_seq)

        contn_pkt = create_contn_pkt(contn_log.fid, contn_payload)
        contn_log.append_pkt(contn_pkt)
        return contn_log
