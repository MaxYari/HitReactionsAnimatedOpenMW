"""Shift every time value in an exported Morrowind .kf (NIF 4.0.0.2).

Why this exists
---------------
The Dremora dissolve is not a script and not a .kf - it is a set of
NiVisController / NiBSPArrayController / NiAlphaController blocks baked into
meshes/r/Dremora.nif, keyed to absolute times 666.667 .. 669.333 (the span of
the mesh's own Death1..Death5 text keys; all five share one animation).

OpenMW drives those non-bone controllers from the animation-time pointer of the
bone group detectBlendMask() assigns them, and every non-bone node falls into
LowerBody. Our death clips own all four bone groups, so OUR clip's time is what
those controllers read. Author a clip at 666.667 and the mesh dissolves itself,
with no edit to the mesh and no engine support needed.

Each clip is its own .kf, so any number of them can occupy that one span.

Only times move. Every value stays 4 bytes, so the file keeps its exact length
and is patched in place.
"""

import struct
import sys

LINEAR, QUADRATIC, TBC, XYZ = 1, 2, 3, 4


class Reader:
    def __init__(self, data):
        self.d = data
        self.o = 0
        self.times = []          # byte offsets of every float that is a time
        self.textkeys = []       # (prefix offset, text offset, length) per text key

    def u32(self):
        v = struct.unpack_from('<I', self.d, self.o)[0]
        self.o += 4
        return v

    def i32(self):
        v = struct.unpack_from('<i', self.d, self.o)[0]
        self.o += 4
        return v

    def u16(self):
        v = struct.unpack_from('<H', self.d, self.o)[0]
        self.o += 2
        return v

    def f32(self):
        v = struct.unpack_from('<f', self.d, self.o)[0]
        self.o += 4
        return v

    def time(self):
        """A float that is a time: remember where it lives, then skip it."""
        self.times.append(self.o)
        return self.f32()

    def string(self):
        prefix = self.o
        n = self.u32()
        s = self.d[self.o:self.o + n]
        self.o += n
        return s.decode('latin1'), prefix, n

    def skip(self, n):
        self.o += n


def read_keys(r, count, key_type, value_floats):
    """A key array: time, value, and whatever the interpolation adds."""
    for _ in range(count):
        r.time()
        r.skip(4 * value_floats)
        if key_type == QUADRATIC:
            r.skip(4 * value_floats * 2)      # forward and backward tangents
        elif key_type == TBC:
            r.skip(4 * 3)                     # tension, bias, continuity


def read_keyframe_data(r):
    rotations = r.u32()
    if rotations:
        rot_type = r.u32()
        if rot_type == XYZ:
            # An unknown float, then three separate float tracks (X, Y, Z),
            # each with its own count and interpolation type.
            r.f32()
            for _ in range(3):
                n = r.u32()
                if n:
                    t = r.u32()
                    read_keys(r, n, t, 1)
        else:
            read_keys(r, rotations, rot_type, 4)
    translations = r.u32()
    if translations:
        read_keys(r, translations, r.u32(), 3)
    scales = r.u32()
    if scales:
        read_keys(r, scales, r.u32(), 1)


def read_block(r, kind):
    if kind == 'NiSequenceStreamHelper':
        r.string()                            # name (always empty in practice)
        r.i32()                               # extra data
        r.i32()                               # controller
    elif kind == 'NiTextKeyExtraData':
        r.i32()                               # next
        r.u32()                               # bytes remaining
        for _ in range(r.u32()):
            r.time()
            _text, prefix, length = r.string()
            r.textkeys.append((prefix, prefix + 4, length))
    elif kind == 'NiStringExtraData':
        r.i32()
        r.u32()
        r.string()
    elif kind == 'NiKeyframeController':
        r.i32()                               # next controller
        r.u16()                               # flags
        r.f32()                               # frequency
        r.f32()                               # phase
        r.time()                              # start time
        r.time()                              # stop time
        r.i32()                               # target
        r.i32()                               # data
    elif kind == 'NiKeyframeData':
        read_keyframe_data(r)
    else:
        raise SystemExit(f'retime_kf: unsupported block {kind!r}')


def scan(data):
    head = data.index(b'\n') + 1
    r = Reader(data)
    r.o = head
    version = r.u32()
    if version != 0x04000002:
        raise SystemExit(f'retime_kf: not a 4.0.0.2 file (version {version:#x})')
    blocks = r.u32()
    for _ in range(blocks):
        read_block(r, r.string()[0])
    # footer: number of root records, then the roots themselves
    roots = r.u32()
    r.skip(4 * roots)
    if r.o != len(data):
        raise SystemExit(f'retime_kf: parsed {r.o} of {len(data)} bytes - refusing to write')
    return r


def retime(data, delta, rename=None):
    """Shift every time by `delta`; with rename=(old, new), also rewrite the
    group name in the text keys.

    The name lives only in NiTextKeyExtraData - the sequence helper's own name is
    empty and bytesRemaining is 0 - so a rename is a splice of those strings and
    their length prefixes, done back to front so earlier offsets stay valid.
    """
    r = scan(data)
    out = bytearray(data)
    for off in r.times:
        struct.pack_into('<f', out, off, struct.unpack_from('<f', data, off)[0] + delta)
    if rename:
        old, new = rename
        for prefix, start, length in reversed(r.textkeys):
            text = bytes(out[start:start + length]).decode('latin1')
            if old not in text:
                continue
            replaced = text.replace(old, new).encode('latin1')
            out[prefix:start + length] = struct.pack('<I', len(replaced)) + replaced
    return bytes(out), len(r.times)


def main():
    if len(sys.argv) not in (4, 6):
        raise SystemExit('usage: retime_kf.py IN.kf OUT.kf DELTA [OLDNAME NEWNAME]')
    src, dst, delta = sys.argv[1], sys.argv[2], float(sys.argv[3])
    rename = (sys.argv[4], sys.argv[5]) if len(sys.argv) == 6 else None
    data = open(src, 'rb').read()
    out, n = retime(data, delta, rename)
    open(dst, 'wb').write(out)
    print(f'{src} -> {dst}: shifted {n} times by {delta:+.3f}')


if __name__ == '__main__':
    main()
