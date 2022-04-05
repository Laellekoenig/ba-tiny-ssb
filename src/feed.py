class Feed:
    """used for managing feed files
    -> append and get packets from feed"""

    def __init__(self, file_name: str):
        self.file = open(file_name, "rb+")
        self.file.seek(0)
        header = self.file.read(128)
        reserved = header[:12]
        self.feed_id = header[12:44]
        self.parent_id = header[44:76]
        self.parent_seq = header[76:80]
        self.anchor_seq = header[80:84]
        self.anchor_mid = header[84:104]
        self.front_seq = header[104:108]
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
        raw_packet = raw_packet[8:] # cut-off reserved 8B
        # TODO: create packet
        return Packet.from_bytes(raw_packet)

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
        self.file.write(bytes(8) + pkt) # pappend 8B reserved
        self.file.flush()

        # update header info
        self.front_seq += 1
        self.front_mid = pkt.msg_id
        self._update_header()

    def append(self, content: bytes) -> bool:
        """creates packet and appends it to the log file"""
        # TODO: adapt dependning on packet implementation
        pkt = Packet.from_bytes(content, self.feed_id, self.front_seq + 1,
                                self.front_mid)
        if pkt is None: return False

        self._append(pkt)
        return True

