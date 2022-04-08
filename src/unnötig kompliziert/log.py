from packet import Packet
from packet import pkt_from_bytes
from ssb_util import file_exists


class Log:
    """used for managing log files
    -> append and get packets from feed"""

    def __init__(self, file_name: str):
        self.file = open(file_name, "rb+")

        header = self.file.read(128)
        # reserved = header[:12]
        self.feed_id = header[12:44]
        self.parent_id = header[44:76]
        self.parent_seq = int.from_bytes(header[76:80], "big")
        self.anchor_seq = int.from_bytes(header[80:84], "big")
        self.anchor_mid = header[84:104]
        self.front_seq = int.from_bytes(header[104:108], "big")
        self.front_mid = header[108:128]

    def __del__(self):
        self.file.close()

    def __getitem__(self, seq: int) -> Packet:
        """gets instance of packet class of corresponding index in feed"""
        if seq > self.front_seq or seq < self.anchor_seq:
            raise IndexError

        pos = 128 * (seq - self.anchor_seq)
        self.file.seek(pos)
        raw_packet = self.file.read(128)
        raw_packet = raw_packet[8:]  # cut-off reserved 8B
        seq = seq.to_bytes(4, "big")  # transform seq number to 4B repr
        return pkt_from_bytes(self.feed_id, seq, self.front_mid, raw_packet)

    def get(self, i: int) -> Packet:
        """same as __getitem__"""
        return self[i]

    def _update_header(self):
        """updates info in file with current params of class"""
        # only thing that changes: front_seq and front_mid:
        header_tail = self.front_seq + self.front_mid
        # go to beginning of file + 104B (parts of header that stay)
        self.file.seek(104)
        self.file.write(header_tail)
        self.file.flush()

    def _append(self, pkt: Packet) -> None:
        """appends given packet to file"""
        # go to end of buffer and write
        self.file.seek(0, 2)
        self.file.write(bytes(8) + pkt)  # pappend 8B reserved
        self.file.flush()

        # update header info
        self.front_seq += 1
        self.front_mid = pkt.mid
        self._update_header()

    def append(self, content: bytes) -> bool:
        """creates packet and appends it to the log file"""
        pkt = pkt_from_bytes(self.feed_id, self.front_seq + 1,
                             self.front_mid, content)

        if pkt is None:
            return False
        self._append(pkt)
        return True


def create_new_log(file_name: str, trusted_seq: int, trusted_mid: str,
                   payload: bytes, parent_fid: bytes = bytes(32),
                   parent_seq: int = 0) -> Log:

    if file_exists(file_name):
        return None

    feed_id = file_name.split(".")[0]
    parent_seq = parent_seq.to_bytes(4, "big")

    assert len(feed_id) == 32, "feed_id must be 32B"
    assert len(parent_fid) == 32, "parent_fid must be 32B"
    assert len(parent_seq) == 4, "parent seq must be 4B"

    # create new log file
    with open(file_name, "wb") as f:
        f.seek(12)  # reserved
        f.write(feed_id)
        f.write(parent_fid)
        f.write(parent_seq)
