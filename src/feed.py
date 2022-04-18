import os
from packet import Blob
from packet import Packet
from packet import PacketType
from packet import create_chain
from packet import pkt_from_bytes
from ssb_util import from_var_int
from ssb_util import is_file
from ssb_util import to_hex


class Feed:
    """
    Represents a .log file.
    Used to get/append data from/to feeds.
    """

    def __init__(self, file_name: str, skey: bytes = None):
        self.file_name = file_name
        f = open(self.file_name, "rb")
        header = f.read(128)
        f.close()
        self.skey = skey

        # reserved = header[:12]
        self.fid = header[12:44]
        self.parent_id = header[44:76]
        self.parent_seq = int.from_bytes(header[76:80], "big")
        self.anchor_seq = int.from_bytes(header[80:84], "big")
        self.anchor_mid = header[84:104]
        self.front_seq = int.from_bytes(header[104:108], "big")
        self.front_mid = header[108:128]

    def __len__(self) -> int:
        return self.front_seq

    def __getitem__(self, seq: int) -> bytes:
        """
        Returns the payload of the packet with the corresponding
        sequence number.
        Negative indices access the feed from behind.
        The packet is NOT validated before the payload is returned.
        Also returns full blobs, without verifying.
        """
        raw_pkt = self.get_raw_pkt(seq)
        # dmx = raw_pkt[:7]
        pkt_type = raw_pkt[7:8]
        payload = raw_pkt[8:56]
        if pkt_type != PacketType.chain20:
            return payload

        # blob chain
        size, num_bytes = from_var_int(payload)
        content = payload[num_bytes:-20]

        ptr = payload[-20:]
        while ptr != bytes(20):
            blob = self._get_blob(ptr)
            assert blob is not None, "failed to extract blob chain"
            ptr = blob.ptr
            content += blob.payload

        return content[:size]

    def get_raw_pkt(self, seq: int) -> bytes:
        """
        Returns the raw packet as bytes.
        The raw packet consists of 8B placeholder and 120B packet wire format.
        """
        if seq < 0:
            seq = self.front_seq + seq + 1  # access last pkt through -1 etc.
        if seq > self.front_seq or seq <= self.anchor_seq:
            raise IndexError

        relative_i = seq- self.anchor_seq
        f = open(self.file_name, "rb")
        f.seek(128 * relative_i)
        raw_pkt = f.read(128)[8:]  # cut off reserved 8B
        f.close()

        return raw_pkt

    def get_pkt_type(self, seq: int) -> bytes:
        """
        Returns the type of the packet with given index.
        Bytes can be compared with PacketTypes.
        """
        raw_pkt = self.get_raw_pkt(seq)
        pkt_type = raw_pkt[7:8]
        types = [PacketType.chain20, PacketType.contdas, PacketType.ischild,
                 PacketType.mkchild]
        try:
            return types[types.index(pkt_type)]
        except Exception:
            return None

    def __iter__(self):
        self._n = self.anchor_seq
        return self

    def __next__(self) -> bytes:
        self._n += 1
        if self._n > self.front_seq:
            raise StopIteration

        payload = self[self._n]
        return payload

    def get(self, i: int) -> bytes:
        """
        Returns Packet instance with corresponding sequence number in feed.
        Identical to __getitem__.
        """
        return self[i]

    def _update_header(self) -> None:
        """
        Updates the front sequence number and message ID in the .log file
        with the current values of the instance.
        """
        assert type(self.front_mid) is bytes
        new_info = self.front_seq.to_bytes(4, "big") + self.front_mid
        assert len(new_info) == 24, "new front seq and mid must be 24B"
        # go to beginning of file + 104B (where front seq and mid are)
        # this is not ideal, since the whole file has to be copied to memory
        # this is due to some weird behaviour of micropython
        f = open(self.file_name, "rb+")
        f.seek(0)
        file_content = f.read()
        updated_content = file_content[:104] + new_info + file_content[128:]
        f.seek(0)
        f.write(updated_content)
        f.close()

    def append_pkt(self, pkt: Packet) -> bool:
        """
        Appends given packet to .log file and updates
        front sequence number and message ID.
        Returns 'True' on success.
        If the feed has ended, nothing is appended and
        False is returned.
        """
        if self.has_ended():
            print("cannot append to finished feed")
            return False

        # TODO: better error handling
        if pkt is None:
            return False

        # go to end of buffer and write
        assert pkt.wire is not None, "packet must be signed before appended"
        payload = bytes(8) + pkt.wire
        assert len(payload) == 128, "wire pkt must be 128B"

        f = open(self.file_name, "rb+")
        f.seek(0, 2)
        f.write(payload)  # pappend 8B reserved
        f.close()

        # update header info
        self.front_seq += 1
        self.front_mid = pkt.mid
        self._update_header()
        return True

    def append_bytes(self, payload: bytes) -> bool:
        """
        Creates a regular packet containing the given payload
        and appends it to the feed.
        Returns 'True' on success.
        If the feed has ended, nothing is appended and
        False is returned.
        """
        next_seq = self.front_seq + 1
        assert self.front_mid is not None
        assert self.skey is not None, "can only append if signing key known"
        pkt = Packet(self.fid, next_seq.to_bytes(4, "big"),
                     self.front_mid, payload, skey=self.skey)
        if pkt is None:
            return False

        return self.append_pkt(pkt)

    def verify_and_append_bytes(self, raw_pkt: bytes) -> bool:
        """
        Creates a new packet from the raw bytes and attempts to validate it.
        Uses the feed_id as validation key.
        If the packet does not validate, False is returned.
        """
        seq = (self.front_seq + 1).to_bytes(4, "big")
        assert self.front_mid is not None
        pkt = pkt_from_bytes(self.fid, seq, self.front_mid, raw_pkt)

        if pkt is None:
            return False

        return self.append_pkt(pkt)

    def append_blob(self, payload: bytes) -> bool:
        """
        Creates a blob from the provided payload.
        A packet of type 'chain20' is appended to the feed,
        referring to the blob files (in _blob directory).
        If the feed has ended, nothing is appended and
        False is returned.
        """
        next_seq = (self.front_seq + 1).to_bytes(4, "big")
        assert self.front_mid is not None
        assert self.skey is not None, "can only append if signing key is known"
        pkt, blobs = create_chain(self.fid, next_seq,
                                  self.front_mid, payload,
                                  self.skey)

        if pkt is None:
            return False

        self.append_pkt(pkt)
        return self._write_blob(blobs)

    def _write_blob(self, blobs: list[Blob]) -> bool:
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

        blobs = []
        ptr = pkt.payload[-20:]
        while ptr != bytes(20):
            blob = self._get_blob(ptr)
            assert blob is not None, "chaining of blobs failed"
            ptr = blob.ptr
            blobs.append(blob)

        return self._verify_chain(pkt, blobs)

    def _verify_chain(self, head: Packet, blobs: list[Blob]) -> bytes:
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
        Returns 'True' if the feed was ended by a 'contdas' packet.
        """
        if len(self) < 1:
            return False
        return self.get_pkt_type(-1) == PacketType.contdas

    def get_parent(self) -> bytes:
        """
        Returns the feed ID of this feed's parent feed.
        If this is not a child feed, 'None' is returned.
        """
        if self.anchor_seq != 0:
            return None

        if self.get_pkt_type(1) != PacketType.ischild:
            return None

        # parent fid == first 32B of payload in first pkt
        return self[1][:32]

    def get_children(self) -> list[bytes]:
        """
        Returns a list of all child feed IDs contained
        within this feed.
        """
        children = []
        for i in range(self.anchor_seq + 1, self.front_seq + 1):
            if self.get_pkt_type(i) == PacketType.mkchild:
                children.append(self[i][:32])

        return children

    def get_contn(self) -> bytes:
        """
        Returns the feed ID of this feed's continuation feed.
        If this feed has not ended, 'None' is returned.
        """
        if self.get_pkt_type(-1) == PacketType.contdas:
            return self[-1][:32]
        else:
            return None

    def get_prev(self) -> bytes:
        """
        Returns the feed ID of this feed's predecessor feed.
        If this feed does not have a predecessor, 'None' is returned.
        """
        if self.anchor_seq != 0:
            return None

        if self.get_pkt_type(1) == PacketType.iscontn:
            return self[1][:32]
        else:
            return None

    def get_front(self) -> tuple[int, bytes]:
        """
        Returns this feed's front sequence number and front message ID
        in a tuple.
        """
        assert self.front_mid is not None
        return (self.front_seq, self.front_mid)
