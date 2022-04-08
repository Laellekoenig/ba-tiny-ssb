import hashlib
PFX = b'tinyssb-0.0.1'


class Packet:

    def __init__(self, feed_id, seq, prev):
        self.feed_id = feed_id
        self.seq = seq
        self.prev = prev
        self.log_name = PFX + self.feed_id + self.seq.to_bytes(4, 'big') + self.prev
        self.dmx = self._dmx(self.log_name)
        self.type = None
        self.payload = None
        self.signature = None
        self.wire = None
        self.msg_id = None
        self.chain_len = -1
        self.chain_content = b''
        self.chain_nextptr = None # hashptr of next (pending) blob

    def _dmx(self, log_name: bytes) -> bytes:
        return hashlib.sha256(log_name).digest()[:7]

    def _msg_id(self, type, payload: bytes, sign_function) -> bytes:
        return hashlib.sha256(self.log_name + self.wire).digest()[:20]

    def _sign(self, type, payload, sign_function):
        assert len(payload) == 48
        self.type = bytes([type])
        self.payload = payload
        msg = self.dmx + self.type + self.payload
        self.signature = signFct(self.log_name + msg)
        self.wire = msg + self.signature
        self.msg_id = self._msg_id()
 
    def predict_next_dmx(self):
        next_name = PFX + self.feed_id + (self.seq + 1).to_bytes(4,'big') + self.msg_id
        return self._dmx(next_name)

    def has_sidechain(self):
        return self.type[0] == PKTTYPE_chain20

    def mk_plain_entry(self, payload, sign_fct):
        if len(payload) < 48:
            payload += b'\x00'*(48-len(payload))
        self._sign(PKTTYPE_plain48, payload[:48], sign_fct)

def from_bytes(buf_120, feed_id, seq, prev, verify_sign_fct):
    pkt = Packet(feed_id, seq, prev)
    if verify_signature_fct: # expected DMX value
        if pkt.dmx != buf120[:7]:
            print("DMX verify failed, not a valid log extension")
            return None
    else: # packet type with no signature
        pkt.dmx = buf_120[:7]
    pkt.type = buf_120[7:8]
    pkt.payload = buf_120[8:56]
    pkt.signature = buf_120[56:]
    if verify_signature_fct: # signature
        if not verify_signature_fct(feed_id, pkt.signature, pkt.log_name + buf_120[:56]):
            print("signature verify failed")
            return None
    pkt.wire = buf_120
    pkt.msg_id = pkt._msg_id() #  only valid if incoming `prev was correct
    return pkt

        
    
    """
    def mk_chain(self, content, sign_fct):
        # fills in and signs this object, returns reversed list of blobs
        # FIXME: use hardisk instead of memory?
        sz = btc_var_int(len(content))
        buf = sz + content
        ptr = bytes(20)
        blobs = []
        if len(buf) <= 28:
            payload = buf + bytes(28-len(buf)) + ptr 
        else:
            head, tail = buf[:28], buf[28:]
            i = len(tail) % 100
            if i > 0:
                tail += bytes(100-i)
            cnt = len(tail)//100
            while len(tail) > 0:
                buf = tail[-100:] + ptr
                blobs.append(buf)
                ptr = blob2hashptr(buf)
                tail = tail[:-100]
            payload = head + ptr 
        self._sign(PKTTYPE_chain20, payload, signFct)
        return blobs

    def undo_chain(self, getBlobFct):
        if self.chain_len < 0:
            self.chain_len, sz = btc_var_int_decode(self.payload)
            self.chain_content = self.payload[sz:min(28,sz+self.chain_len)]
            if self.chain_len == len(self.chain_content):
                self.chain_nextptr = None
            else:
                self.chain_nextptr = self.payload[-20:]
            if self.chain_nextptr == bytes(20):
                self.chain_nextptr = None
        while getBlobFct and self.chain_len > len(self.chain_content) \
                         and self.chain_nextptr:
            blob = getBlobFct(self.chain_nextptr)
            if blob == None: return False
            self.chain_nextptr = blob[100:]
            if self.chain_nextptr == bytes(20): self.chain_nextptr = None
            blob = blob[:min(100,self.chain_len - len(self.chain_content))]
            self.chain_content += blob
        return self.chain_len == len(self.chain_content) # all content found
"""
# ----------------------------------------------------------------------

"""
def blob2hashptr(blob):
    return hashlib.sha256(blob).digest()[:20]

def from_bytes(buf120, fid, seq, prev, verify_signature_fct):
    # converts bytes to a packet object, if it verifies or if flag is False
    pkt = PACKET(fid, seq, prev)
    if verify_signature_fct: # expected DMX value
        if pkt.dmx != buf120[:7]:
            print("DMX verify failed, not a valid log extension")
            return None
    else:
        pkt.dmx = buf120[:7]
    pkt.typ = buf120[7:8]
    pkt.payload = buf120[8:56]
    pkt.signature = buf120[56:]
    if verify_signature_fct: # signature
        if not verify_signature_fct(fid, pkt.signature, pkt.nam + buf120[:56]):
            print("signature verify failed")
            return None
    pkt.wire = buf120
    pkt.mid = pkt._mid() #  only valid if incoming `prev was correct
    return pkt

def btc_var_int(i):
    assert i >= 0
    if i <= 252:        return bytes((i,))
    if i <= 0xffff:     return b'\xfd' + i.to_bytes(2, 'little')
    if i <= 0xffffffff: return b'\xfe' + i.to_bytes(4, 'little')
    return                     b'\xff' + i.to_bytes(8, 'little')

def btc_var_int_decode(buf):
    assert len(buf) >= 1
    h = buf[0]
    if h <= 252: return (h,1)
    assert len(buf) >= 3
    if h == 0xfd: return (int.from_bytes(buf[1:3], 'little'),3)
    assert len(buf) >= 5
    if h == 0xfe: return (int.from_bytes(buf[1:5], 'little'),5)
    assert len(buf) >= 9
    return (int.from_bytes(buf[1:9], 'little'), 9)

"""  
