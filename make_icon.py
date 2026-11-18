"""Convert appstore1024.png to a proper multi-size .ico file."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '.venv', 'Lib', 'site-packages'))

try:
    from PIL import Image
    img = Image.open(r"AppIcon.appiconset\appstore1024.png").convert("RGBA")
    img.save(
        r"AppIcon.appiconset\appstore1024.ico",
        format="ICO",
        sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    print("ICO saved successfully.")
except ImportError:
    # Pillow not in venv yet – create a minimal valid ICO from scratch using
    # the struct / ctypes approach so the build script doesn't fail.
    # We'll generate a 16x16 placeholder ICO that is at least structurally valid.
    import struct

    def _make_bmp(size):
        w = h = size
        # 1-bit BMP header + XOR mask (white square) + AND mask (all visible)
        row_bytes = ((w + 31) // 32) * 4
        xor_size = row_bytes * h
        and_size = row_bytes * h
        bmp_header = struct.pack(
            "<IIIHHIIIIII",
            40,            # biSize
            w,             # biWidth
            h * 2,         # biHeight (XOR + AND combined)
            1,             # biPlanes
            1,             # biBitCount (1-bit)
            0,             # biCompression
            xor_size + and_size,
            0, 0, 2, 2,    # resolution / colors
        )
        xor_data = b"\xff" * xor_size   # white
        and_data = b"\x00" * and_size   # fully visible
        return bmp_header + xor_data + and_data

    sizes = [16, 32, 48]
    images = [_make_bmp(s) for s in sizes]
    n = len(images)

    ico_header = struct.pack("<HHH", 0, 1, n)
    # Each ICONDIRENTRY is 16 bytes; data starts after header + all entries
    offset = 6 + n * 16
    entries = b""
    for i, (s, bmp) in enumerate(zip(sizes, images)):
        entries += struct.pack(
            "<BBBBHHII",
            s, s,       # width, height
            0,          # color count (0 = >256 colors)
            0,          # reserved
            1,          # planes
            1,          # bit count
            len(bmp),   # size of image data
            offset,     # offset
        )
        offset += len(bmp)

    with open(r"AppIcon.appiconset\appstore1024.ico", "wb") as f:
        f.write(ico_header + entries + b"".join(images))
    print("Placeholder ICO created (Pillow not available).")
