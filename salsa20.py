import sys
import struct
import random
import math


def text2matrix(text):
    matrix = []
    for i in range(16):
        byte = (text >> (8 * (15 - i))) & 0xFF
        if i % 4 == 0:
            matrix.append([byte])
        else:
            matrix[int(i / 4)].append(byte)
    return matrix


def matrix2text(matrix):
    text = 0
    for i in range(4):
        for j in range(4):
            text |= (matrix[i][j] << (120 - 8 * (4 * i + j)))
    return text

#convert bytes -> long and long -> bytes
def long_to_bytes(n, blocksize=0):

    if n < 0 or blocksize < 0:
        raise ValueError("Values must be non-negative")

    result = []
    pack = struct.pack

    # Fill the first block independently from the value of n
    bsr = blocksize
    while bsr >= 8:
        result.insert(0, pack('>Q', n & 0xFFFFFFFFFFFFFFFF))
        n = n >> 64
        bsr -= 8

    while bsr >= 4:
        result.insert(0, pack('>I', n & 0xFFFFFFFF))
        n = n >> 32
        bsr -= 4

    while bsr > 0:
        result.insert(0, pack('>B', n & 0xFF))
        n = n >> 8
        bsr -= 1

    if n == 0:
        if len(result) == 0:
            bresult = b'\x00'
        else:
            bresult = b''.join(result)
    else:
        # The encoded number exceeds the block size
        while n > 0:
            result.insert(0, pack('>Q', n & 0xFFFFFFFFFFFFFFFF))
            n = n >> 64
        result[0] = result[0].lstrip(b'\x00')
        bresult = b''.join(result)
        # bresult has minimum length here
        if blocksize > 0:
            target_len = ((len(bresult) - 1) // blocksize + 1) * blocksize
            bresult = b'\x00' * (target_len - len(bresult)) + bresult

    return bresult


def bytes_to_long(s):
    """Convert a byte string to a long integer (big endian).
    In Python 3.2+, use the native method instead::
        >>> int.from_bytes(s, 'big')
    For instance::
        >>> int.from_bytes(b'\x00P', 'big')
        80
    This is (essentially) the inverse of :func:`long_to_bytes`.
    """
    acc = 0

    unpack = struct.unpack

    # Up to Python 2.7.4, struct.unpack can't work with bytearrays nor
    # memoryviews
    if sys.version_info[0:3] < (2, 7, 4):
        if isinstance(s, bytearray):
            s = bytes(s)
        elif isinstance(s, memoryview):
            s = s.tobytes()

    length = len(s)
    if length % 4:
        extra = (4 - length % 4)
        s = b'\x00' * extra + s
        length = length + extra
    for i in range(0, length, 4):
        acc = (acc << 32) + unpack('>I', s[i:i+4])[0]
    return acc

class Salsa20():
    def __init__(self, key, nonce) -> None:
        #các giá trị đầu vào bao gồm key 32-byte và nonce được chọn random
        self._key = key
        self._nonce = nonce
        self.ctr = b'\x00'*8

    def _xor(self, a: bytes, b: bytes) -> bytes:
        return bytes([x ^ y for x, y in zip(a, b)])
    
    #row and column round
    '''
    thuật toán thực tế là thực hiện thông qua quarter round cho hàng và cột
    If x is a 4-word input:
    x = (x0, x1, x2, x3)
    then the function can be defined as follow:
    quarterround(x) = (y0, y1, y2, y3)
    where:
    y1 = x1 XOR ((x0 + x3) <<< 7)
    y2 = x2 XOR ((y1 + x0) <<< 9)
    y3 = x3 XOR ((y2 + y1) <<< 13)
    y0 = x0 XOR ((y3 + y2) <<< 18)
    '''
    def qr(self, a, b, c, d):
        b ^= self.ROTL(a+d, 7)
        c ^= self.ROTL(b+a, 9)
        d ^= self.ROTL(c+b,13)
        a ^= self.ROTL(d+c,18)
        return a, b, c, d

    def ROTL(self, x, y):
        return (((x) << (y)) & 0xFFFFFFFF) | ((x) >> (32 - (y)))
    

    #row round function
    '''
    f x is a 16-word input:
    x = (x0, x1, x2, ..., x15)
    then the function can be defined as follow:
    rowround(x) = (y0, y1, y2, ..., y15)
    where:
    (y0, y1, y2, y3) = quarterround(x0, x1, x2, x3)
    (y5, y6, y7, y4) = quarterround(x5, x6, x7, x4)
    (y10, y11, y8, y9) = quarterround(x10, x11, x8, x9)
    (y15, y12, y13, y14) = quarterround(x15, x12, x13, x14)
    
    '''
    def shift_row(self, s):
            s[0][0], s[1][0], s[2][0], s[3][0] = self.qr(s[0][0], s[1][0], s[2][0], s[3][0])
            s[1][1], s[2][1], s[3][1], s[0][1] = self.qr(s[1][1], s[2][1], s[3][1], s[0][1])
            s[2][2], s[3][2], s[0][2], s[1][2] = self.qr(s[2][2], s[3][2], s[0][2], s[1][2])
            s[3][3], s[0][3], s[1][3], s[2][3] = self.qr(s[3][3], s[0][3], s[1][3], s[2][3])
            return s

    #column round function
    '''
    x = (x0, x1, x2, ..., x15)
    then the function can be defined as follow:
    rowround(x) = (y0, y1, y2, ..., y15)
    where:
    (y0, y1, y2, y3) = quarterround(x0, x1, x2, x3)
    (y5, y6, y7, y4) = quarterround(x5, x6, x7, x4)
    (y10, y11, y8, y9) = quarterround(x10, x11, x8, x9)
    (y15, y12, y13, y14) = quarterround(x15, x12, x13, x14)
    '''
    def shift_column(self, s):
        s[0][0], s[0][1], s[0][2], s[0][3] = self.qr(s[0][0], s[0][1], s[0][2], s[0][3])
        s[1][1], s[1][2], s[1][3], s[1][0] = self.qr(s[1][1], s[1][2], s[1][3], s[1][0])
        s[2][2], s[2][3], s[2][0], s[2][1] = self.qr(s[2][2], s[2][3], s[2][0], s[2][1])
        s[3][3], s[3][0], s[3][1], s[3][2] = self.qr(s[3][3], s[3][0], s[3][1], s[3][2])
        return s
    
    def key_expansion(self):   
        inp = b'expa' + self._key[:16] + b'nd 3' + self._nonce + self.ctr + b'2-by' + self._key[16:] + b'te k'
        inp = text2matrix(bytes_to_long(inp))
        x = inp
        for i in range(10):
            inp = self.shift_column(inp)
            inp = self.shift_row(inp)
        
        val = b''
        for i in range(4):
            for j in range(4):
                inp[i][j] = (inp[i][j] + x[i][j]) % (2**32)
                val += long_to_bytes(inp[i][j])
        return val

    def encrypt(self, msg):
        key_gen = b''
        for i in range(math.ceil(len(msg)/64)):
            key_gen += self.key_expansion()
            self.ctr = bytes_to_long(self.ctr) + 1
            self.ctr = long_to_bytes(self.ctr)
        cipher = self._xor(msg, key_gen[:len(msg)])
        return cipher
    
key = b'this is 32-byte key for salsa 20'
nonce = b'rd64bits'
salsa = Salsa20(key, nonce)

msg = b'minh nghia iotminh nghia iotminh nghia iotminh nghia iotminh nghia iotminh nghia iotminh nghia iotminh nghia iot'
cipher = salsa.encrypt(msg)

print(cipher, len(cipher), len(msg))

