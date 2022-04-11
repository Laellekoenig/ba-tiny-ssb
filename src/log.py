from packet import Packet
from packet import pkt_from_bytes
from packet import make_chain
from packet import Blob
from packet import PacketType
from ssb_util import to_hex
import os
from ssb_util import is_file
from ssb_util import from_var_int


class Log:
    """used for managing log files
    -> append and get packets from feed"""

    def __init__(self, file_name: str):
        self.file_name = file_name
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
        self._mids = self._get_mids()  # used for accessing packets quickly

    def __len__(self) -> int:
        return self.front_seq

    def __del__(self):
        self.file.close()

    def __getitem__(self, seq: int) -> Packet:
        """gets instance of packet class of corresponding index in feed"""
        if seq < 0:
            seq = self.front_seq + seq  # access last pkt through -1 etc
        if seq > self.front_seq or seq <= self.anchor_seq:
            raise IndexError

        relative_seq = seq - self.anchor_seq

        self.file.seek(128 * relative_seq)
        raw_pkt = self.file.read(128)[8:]  # cut off reserved 8B
        return pkt_from_bytes(self.feed_id, seq.to_bytes(4, "big"),
                              self._mids[relative_seq - 1], raw_pkt)

    def __iter__(self):
        self._n = self.anchor_seq
        return self

    def __next__(self) -> Packet:
        self._n += 1
        if self._n > self.front_seq:
            raise StopIteration

        pkt = self[self._n]
        return pkt

    def get(self, i: int) -> Packet:
        """same as __getitem__"""
        return self[i]

    def get_payload(self, i: int) -> bytes:
        pkt = self[i]
        if pkt.pkt_type == PacketType.plain48:
            return pkt.payload
        if pkt.pkt_type == PacketType.chain20:
            return self.get_blob_chain(pkt)

        # TODO: other pkt types
        return None

    def _get_mids(self) -> [bytes]:
        """loops over all log entries and returns their mids in a list
        also confirms every packet"""
        mids = [self.feed_id[:20]]
        # loop over all log entries and get their mids
        # TODO: error when packet cannot be confirmed
        for i in range(self.anchor_seq + 1, self.front_seq + 1):
            self.file.seek(128 * (i - self.anchor_seq))
            raw_pkt = self.file.read(128)[8:]
            pkt = pkt_from_bytes(self.feed_id, i.to_bytes(4, "big"),
                                 mids[-1], raw_pkt)
            mids.append(pkt.mid)

        return mids

    def _update_header(self) -> None:
        """updates info in file with current params of class"""
        # only thing that changes: front_seq and front_mid:
        updated_info = self.front_seq.to_bytes(4, "big") + self.front_mid
        assert len(updated_info) == 24, "new front seq and mid must be 24B"
        # go to beginning of file + 104B (where front seq and mid are)
        self.file.seek(104)
        self.file.write(updated_info)
        self.file.flush()

    def _append(self, pkt: Packet) -> None:
        """appends given packet to file"""
        # go to end of buffer and write
        self.file.seek(0, 2)
        self.file.write(bytes(8) + pkt.wire)  # pappend 8B reserved
        self.file.flush()

        # update header info
        self.front_seq += 1
        self.front_mid = pkt.mid
        self._update_header()

    def append_pkt(self, pkt: Packet) -> bool:
        """appends packet to the log file"""
        if pkt is None:
            return False
        self._append(pkt)
        return True

    def append_payload(self, payload: bytes) -> bool:
        """creates packet containing payload and appends it to log"""
        next_seq = self.front_seq + 1
        pkt = Packet(self.feed_id, next_seq.to_bytes(4, "big"),
                     self.front_mid, payload)
        if pkt is None:
            return False

        self._append(pkt)
        return True

    def append_blob(self, payload: bytes) -> bool:
        """creates a blob-chain from the provided bytes
        the first blob is saved as a packet of type chain20 in the log
        the remaining blobs are saved to the blob dir"""
        next_seq = (self.front_seq + 1).to_bytes(4, "big")
        pkt, blobs = make_chain(self.feed_id, next_seq,
                                self.front_mid, payload)

        if pkt is None:
            return False

        self._append(pkt)
        # save blobs
        return self._write_blobs(blobs)

    def _write_blobs(self, blobs: [Blob]) -> bool:
        """takes a list of blobs and writes them
        as files as defined in tinyssb protocol"""
        # get path of _blobs folder
        split = self.file_name.split("/")
        path = "/".join(split[:-2]) + "_blobs/"

        for blob in blobs:
            hash_hex = to_hex(blob.signature)
            dir_path = path + hash_hex[:2]
            file_name = dir_path + "/" + hash_hex[2:]
            if not is_file(dir_path):
                print(dir_path)
                os.mkdir(dir_path)
            try:
                f = open(file_name, "wb")
                f.write(blob.wire)
                f.close()
            except Exception:
                return False
        return True

    def _get_blob(self, ptr: bytes) -> Blob:
        """reads the blob file that the provided ptr is pointing to
        returns the blob instance of the file"""
        # get path of _blobs folder
        hex_hash = to_hex(ptr)
        split = self.file_name.split("/")
        file_name = "/".join(split[:-2]) + "_blobs/" + hex_hash[:2]
        file_name += "/" + hex_hash[2:]

        try:
            f = open(file_name, "rb")
            content = f.read(120)
            f.close()
        except Exception:
            return None

        assert len(content) == 120, "blob must be 120B"
        return Blob(content[:100], content[100:])

    def get_blob_chain(self, pkt: Packet) -> bytes:
        """retrieves the validated blob content for a given blob header pkt"""
        assert pkt.pkt_type == PacketType.chain20, "pkt type must be chain20"
        size, num_bytes = from_var_int(pkt.payload)
        ptr = pkt.payload[-20:]

        blobs = []
        while ptr != bytes(20):
            blob = self._get_blob(ptr)
            ptr = blob.ptr
            blobs.append(blob)

        return self._verify_chain(pkt, blobs)

    def _verify_chain(self, head: Packet, blobs: [Blob]) -> bytes:
        """verifies the authenticity of the given blob chain
        if it is valid, the content is returned as bytes"""
        size, num_bytes = from_var_int(head.payload)
        ptr = head.payload[-20:]
        content = head.payload[num_bytes:-20]

        for blob in blobs:
            if ptr != blob.signature:
                return None
            content += blob.payload
            ptr = blob.ptr

        return content[:size]
