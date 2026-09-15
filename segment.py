# segment.py
import struct

class Segment:
    HEADER_FORMAT = '!IIHHH'
    HEADER_SIZE = struct.calcsize(HEADER_FORMAT)

    SYN = 0b1000
    ACK = 0b0100
    FIN = 0b0010
    DAT = 0b0001

    def __init__(self, seq_num=0, ack_num=0, flags=0, window=0, data=b''):
        self.seq_num = seq_num
        self.ack_num = ack_num
        self.flags = flags
        self.window = window
        self.checksum = 0
        self.data = data

    def calc_checksum(self):
        temp_header = struct.pack(self.HEADER_FORMAT, self.seq_num, self.ack_num, self.flags, self.window, 0)
        msg = temp_header + self.data
        if len(msg) % 2 == 1:
            msg += b'\0'
        s = 0
        for i in range(0, len(msg), 2):
            w = (msg[i] << 8) + msg[i+1]
            s += w
        s = (s >> 16) + (s & 0xffff)
        s = s + (s >> 16)
        return (~s) & 0xffff

    def serialize(self):
        self.checksum = self.calc_checksum()
        header = struct.pack(self.HEADER_FORMAT, self.seq_num, self.ack_num, self.flags, self.window, self.checksum)
        return header + self.data

    @classmethod
    def deserialize(cls, raw_bytes):
        header = raw_bytes[:cls.HEADER_SIZE]
        data = raw_bytes[cls.HEADER_SIZE:]
        seq_num, ack_num, flags, window, checksum = struct.unpack(cls.HEADER_FORMAT, header)
        seg = cls(seq_num, ack_num, flags, window, data)
        seg.checksum = checksum
        return seg

    def is_corrupt(self):
        return self.calc_checksum() != self.checksum
    