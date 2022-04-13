import os
from packet import Blob
from packet import Packet
from packet import PacketType
from packet import create_chain
from packet import pkt_from_bytes
from ssb_util import from_var_int
from ssb_util import is_file
from ssb_util import to_hex


class Log:
    """
    Represents a .log file.
    Used to get/appennd data from/to logs.
    """

    def __init__(self, file_name: str):
        self.file_name = file_name
        self.file = open(file_name, "rb+")

        header = self.file.read(128)
        # reserved = header[:12]
        self.fid = header[12:44]
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
        """
        Returns Packet instance with corresponding sequence number in feed.
        Negative indices retrieve packets starting from
        the latest sequence number.
        Packets are confirmed before they are returned.
        """
        if seq < 0:
            seq = self.front_seq + seq + 1  # access last pkt through -1 etc.
        if seq > self.front_seq or seq <= self.anchor_seq:
            raise IndexError

        relative_seq = seq - self.anchor_seq

        self.file.seek(128 * relative_seq)
        raw_pkt = self.file.read(128)[8:]  # cut off reserved 8B
        return pkt_from_bytes(self.fid, seq.to_bytes(4, "big"),
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
        """
        Returns Packet instance with corresponding sequence number in feed.
        Identical to __getitem__.
        """
        return self[i]

    def get_bytes_quick(self, i: int) -> bytes:
        """
        Returns the payload of the packet with the corresponding
        sequence number.
        Negative indices access the log from behind.
        The packet is NOT validated before the payload is returned.
        This is quicker than get_bytes.
        Does not return full blobs.
        """
        if i < 0:
            i = self.front_seq + i + 1  # access last pkt through -1 etc.
        if i > self.front_seq or i <= self.anchor_seq:
            raise IndexError

        relative_i = i - self.anchor_seq

        self.file.seek(128 * relative_i)
        raw_pkt = self.file.read(128)[8:]  # cut off reserved 8B
        return raw_pkt[8:56]

    def get_bytes(self, i: int) -> bytes:
        """
        Returns the packet-specific payload as bytes.
        The packet is validated before the payload is returned.
        """
        """returns the packet-specific payload
        returns full blob messages as bytes"""
        # TODO: more packet-specific handeling
        pkt = self[i]
        if pkt is None:
            return None

        if pkt.pkt_type == PacketType.plain48:
            return pkt.payload
        if pkt.pkt_type == PacketType.chain20:
            return self.get_blob_chain(pkt)
        if pkt.pkt_type == PacketType.ischild:
            return pkt.payload
        if pkt.pkt_type == PacketType.iscontn:
            return pkt.payload
        if pkt.pkt_type == PacketType.mkchild:
            return pkt.payload
        if pkt.pkt_type == PacketType.contdas:
            return pkt.payload

        return None

    def _get_mids(self) -> [bytes]:
        """
        Loops over all log entries and returns their message IDs as a list.
        Used for speeding-up packet validation.
        Confirms every packet in the log.
        """
        mids = [self.fid[:20]]
        # TODO: error when packet cannot be confirmed
        for i in range(self.anchor_seq + 1, self.front_seq + 1):
            self.file.seek(128 * (i - self.anchor_seq))
            raw_pkt = self.file.read(128)[8:]
            pkt = pkt_from_bytes(self.fid, i.to_bytes(4, "big"),
                                 mids[-1], raw_pkt)
            mids.append(pkt.mid)

        return mids

    def _update_header(self) -> None:
        """
        Updates the front sequence number and message ID in the .log file
        with the current values of the instance.
        """
        updated_info = self.front_seq.to_bytes(4, "big") + self.front_mid
        assert len(updated_info) == 24, "new front seq and mid must be 24B"
        # go to beginning of file + 104B (where front seq and mid are)
        self.file.seek(104)
        self.file.write(updated_info)
        self.file.flush()

    def append_pkt(self, pkt: Packet) -> bool:
        """
        Appends given packet to .log file and updates
        front sequence number and message ID.
        Returns 'True' on success.
        """
        # TODO: better error handeling
        if pkt is None:
            return False
        # go to end of buffer and write
        assert len(bytes(8) + pkt.wire) == 128, "wire pkt must be 128B"
        self.file.seek(0, 2)
        self.file.write(bytes(8) + pkt.wire)  # pappend 8B reserved
        self.file.flush()

        # update header info
        self.front_seq += 1
        self.front_mid = pkt.mid
        self._update_header()
        self._mids.append(pkt.mid)
        return True

    def append_bytes(self, payload: bytes) -> bool:
        """
        Creates a regular packet containing the given payload
        and appends it to the log.
        Returns 'True' on success.
        """
        next_seq = self.front_seq + 1
        pkt = Packet(self.fid, next_seq.to_bytes(4, "big"),
                     self.front_mid, payload)
        if pkt is None:
            return False

        self.append_pkt(pkt)
        return True

    def append_blob(self, payload: bytes) -> bool:
        """
        Creates a blob from the provided payload.
        A packet of type 'chain20' is appended to the log,
        refering to the blob files (in _blob directory).
        """
        next_seq = (self.front_seq + 1).to_bytes(4, "big")
        pkt, blobs = create_chain(self.fid, next_seq,
                                  self.front_mid, payload)

        if pkt is None:
            return False

        self.append_pkt(pkt)
        return self._write_blob(blobs)

    def _write_blob(self, blobs: [Blob]) -> bool:
        """
        Takes a list of blob instances and writes them
        to blob files, as defined in tiny-ssb protocol.
        Returns 'True' on success.
        """
        # get path of _blobs folder
        split = self.file_name.split("/")
        path = "/".join(split[:-2]) + "_blobs/"

        for blob in blobs:
            hash_hex = to_hex(blob.signature)
            dir_path = path + hash_hex[:2]
            file_name = dir_path + "/" + hash_hex[2:]
            if not is_file(dir_path):
                os.mkdir(dir_path)
            try:
                f = open(file_name, "wb")
                f.write(blob.wire)
                f.close()
            except Exception:
                return False
        return True

    def _get_blob(self, ptr: bytes) -> Blob:
        """
        Creates and returns a blob instance of the
        blob file that the given pointer is pointing to.
        """
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
        """
        Retrieves the full data that a 'chain20' packet is pointing to.
        The content is validated.
        If validation fails, 'None' is returned.
        """
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
        """
        Verifies the authenticity of a given blob chain.
        If it is valid, the content is returned as bytes.
        """
        size, num_bytes = from_var_int(head.payload)
        ptr = head.payload[-20:]
        content = head.payload[num_bytes:-20]

        for blob in blobs:
            if ptr != blob.signature:
                return None
            content += blob.payload
            ptr = blob.ptr

        return content[:size]

    def has_ended(self) -> bool:
        """
        Returns 'True' if the log was ended by a 'contdas' packet.
        """
        last_pkt = self[-1]
        return last_pkt.pkt_type == PacketType.contdas

    def get_parent(self) -> bytes:
        """
        Returns the feed ID of this feed's parent feed.
        If this is not a child feed, 'None' is returned.
        """
        if self.anchor_seq != 0:
            return None

        first_pkt = self[1]
        if first_pkt.pkt_type != PacketType.ischild:
            return None

        return first_pkt.payload[:32]

    def get_children(self) -> [bytes]:
        """
        Returns a list of all child feed IDs contained
        within this log.
        """
        children = []
        for pkt in self:
            if pkt.pkt_type == PacketType.mkchild:
                children.append(pkt)

        # extract feed ids
        return [pkt.payload[:32] for pkt in children]

    def get_contn(self) -> bytes:
        """
        Returns the feed ID of this log's continuation feed.
        If this feed has not ended, 'None' is returned.
        """
        last_pkt = self[-1]
        if last_pkt.pkt_type != PacketType.contdas:
            return None

        return last_pkt.payload[:32]

    def get_prev(self) -> bytes:
        """
        Returns the feed ID of this log's predecessor feed.
        If this feed does not have a predecessor, 'None' is returned.
        """
        try:
            first_pkt = self[1]
        except Exception:
            return None

        if first_pkt.pkt_type != PacketType.iscontn:
            return None

        return first_pkt.payload[:32]
