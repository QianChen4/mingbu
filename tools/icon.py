"""画软件图标（蓝色渐变底、白色账本、三根上升的柱子，不带文字）。

    python3 tools/icon.py          # 生成 assets/app.png、app.ico、app.icns 和 web/ 里的图标

需要 Pillow（只在打包时用，软件运行不需要）。
"""
import os
import sys

from PIL import Image, ImageDraw, ImageFilter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
S = 1024


def lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(len(a)))


def rounded_mask(size, box, r):
    m = Image.new('L', size, 0)
    ImageDraw.Draw(m).rounded_rectangle(box, r, fill=255)
    return m


def draw(size=S):
    k = size / S
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    # 底：圆角方块，上浅下深的蓝色渐变
    pad = int(40 * k)
    grad = Image.new('RGBA', (size, size))
    gd = ImageDraw.Draw(grad)
    top, bottom = (84, 150, 236), (30, 78, 176)
    for y in range(size):
        gd.line([(0, y), (size, y)], fill=lerp(top, bottom, y / (size - 1)) + (255,))
    img.paste(grad, (0, 0), rounded_mask((size, size), (pad, pad, size - pad, size - pad), int(220 * k)))
    # 账本的阴影
    bx0, by0, bx1, by1 = int(232 * k), int(196 * k), int(792 * k), int(828 * k)
    sh = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle((bx0 + 6 * k, by0 + 22 * k, bx1 + 6 * k, by1 + 22 * k), int(48 * k), fill=(10, 30, 80, 110))
    sh = sh.filter(ImageFilter.GaussianBlur(28 * k))
    img.alpha_composite(sh)
    # 白色账本 + 左边浅蓝的书脊
    book = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    bd = ImageDraw.Draw(book)
    bd.rounded_rectangle((bx0, by0, bx1, by1), int(48 * k), fill=(255, 255, 255, 255))
    spine = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(spine).rectangle((bx0, by0, bx0 + int(84 * k), by1), fill=(220, 233, 250, 255))
    book.alpha_composite(Image.composite(spine, Image.new('RGBA', (size, size), (0, 0, 0, 0)),
                                         rounded_mask((size, size), (bx0, by0, bx1, by1), int(48 * k))))
    bd = ImageDraw.Draw(book)
    # 三根上升的柱子
    base = int(706 * k)
    w = int(78 * k)
    for x, h, col in ((404, 172, (140, 192, 255)), (530, 280, (92, 158, 245)), (656, 410, (40, 106, 232))):
        x = int(x * k)
        bd.rounded_rectangle((x, base - int(h * k), x + w, base), int(16 * k), fill=col + (255,))
    img.alpha_composite(book)
    return img


def main():
    big = draw(S)
    assets = os.path.join(ROOT, 'assets')
    os.makedirs(assets, exist_ok=True)
    big.save(os.path.join(assets, 'app.png'))
    big.save(os.path.join(ROOT, 'web', 'app.png'))
    big.resize((64, 64), Image.LANCZOS).save(os.path.join(ROOT, 'web', 'favicon.png'))
    sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    big.save(os.path.join(assets, 'app.ico'), sizes=sizes)
    big.save(os.path.join(ROOT, 'web', 'app.ico'), sizes=sizes)
    try:
        big.save(os.path.join(assets, 'app.icns'))
    except Exception as e:  # 老版本 Pillow 不支持 icns
        print('没有生成 app.icns：', e, file=sys.stderr)
    print('图标已生成：', assets)


if __name__ == '__main__':
    main()
