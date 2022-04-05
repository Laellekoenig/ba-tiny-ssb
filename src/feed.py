class Feed:

    def __init__(self, file_name: str):
        self.file = open(file_name, "rb+")
        # self.file.seek(0)
        header = self.file.read(128)
        reserved = header[:12]
        self.feed_id = header[12:44]
        self.parent_id = header[44:76]
        self.parent_seq = header[76:80]
        self.anchor_seq = header[80:84]
        self.anchor_mid = header[84:104]
        self.front_seq = header[104:108]
        self.front_mid = header[108:128]

