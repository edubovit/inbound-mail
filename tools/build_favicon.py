import struct
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def chunk(kind, data):
    return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))


def image(size):
    pixels = bytearray()
    for y in range(size):
        pixels.append(0)
        for x in range(size):
            px, py = (x + .5) * 32 / size, (y + .5) * 32 / size
            arrow = (14 <= px < 18 and 6 <= py < 19) or (19 <= py < 27 and abs(px - 16) <= 27 - py)
            pixels.extend((241, 241, 235, 255) if arrow else (225, 81, 61, 255))
    header = struct.pack('>IIBBBBB', size, size, 8, 6, 0, 0, 0)
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', header) + chunk(b'IDAT', zlib.compress(pixels)) + chunk(b'IEND', b'')


def main():
    sizes = (16, 32, 48)
    images = [image(size) for size in sizes]
    offset = 6 + 16 * len(sizes)
    directory = bytearray(struct.pack('<HHH', 0, 1, len(sizes)))
    for size, data in zip(sizes, images):
        directory.extend(struct.pack('<BBBBHHII', size, size, 0, 0, 1, 32, len(data), offset))
        offset += len(data)
    (ROOT / 'mailserver/static/favicon.ico').write_bytes(directory + b''.join(images))


if __name__ == '__main__':
    main()
