# -*- coding: utf-8 -*-
"""生成网易云音乐工具箱 favicon.ico

设计：圆角方形渐变底（网易云红 #EC4141 -> 暖橙 #FF7A59），
中央为白色八分音符 + 右下小播放三角点缀，多尺寸输出。
"""
from PIL import Image, ImageDraw
import math

S = 256  # 主画布尺寸
img = Image.new("RGBA", (S, S), (0, 0, 0, 0))

# ---- 渐变底（对角线渐变）----
grad = Image.new("RGBA", (S, S))
c1 = (236, 65, 65)    # 网易云红
c2 = (255, 138, 92)   # 暖橙
for y in range(S):
    for x in range(0, S, 4):  # 步长4加速，横向渐变平滑足够
        t = (x + y) / (2 * S - 2)
        r = int(c1[0] + (c2[0] - c1[0]) * t)
        g = int(c1[1] + (c2[1] - c1[1]) * t)
        b = int(c1[2] + (c2[2] - c1[2]) * t)
        for dx in range(4):
            if x + dx < S:
                grad.putpixel((x + dx, y), (r, g, b, 255))

# ---- 圆角遮罩 ----
mask = Image.new("L", (S, S), 0)
md = ImageDraw.Draw(mask)
md.rounded_rectangle([0, 0, S - 1, S - 1], radius=56, fill=255)
img.paste(grad, (0, 0), mask)

draw = ImageDraw.Draw(img)
WHITE = (255, 255, 255, 255)

# ---- 八分音符 ----
head_cx, head_cy = 96, 178
head_rx, head_ry = 40, 31
# 符头：实心旋转椭圆（小图层绘制后旋转粘贴）
head = Image.new("RGBA", (110, 90), (0, 0, 0, 0))
hd = ImageDraw.Draw(head)
hd.ellipse([10, 10, 100, 80], fill=WHITE)
head = head.rotate(20, resample=Image.BICUBIC, expand=True)
img.paste(head, (head_cx - head.width // 2, head_cy - head.height // 2), head)

# 符杆：从头右侧向上
stem_x = head_cx + head_rx - 7
draw.rounded_rectangle([stem_x, 60, stem_x + 14, 182], radius=7, fill=WHITE)

# 符尾：平滑飘旗（多段采样二次贝塞尔曲线）
def quad(p0, p1, p2, steps=24):
    return [
        (
            (1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * p1[0] + t ** 2 * p2[0],
            (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * p1[1] + t ** 2 * p2[1],
        )
        for t in [i / steps for i in range(steps + 1)]
    ]

top = (stem_x + 14, 60)
outer = quad(top, (stem_x + 78, 92), (stem_x + 44, 150))       # 外弧
inner = quad((stem_x + 44, 150), (stem_x + 56, 108), top)      # 内弧
draw.polygon(outer + inner, fill=WHITE)

# ---- 右下角播放三角点缀 ----
tri_cx, tri_cy, r = 196, 190, 34
# 半透明白圆底
overlay = Image.new("RGBA", (S, S), (0, 0, 0, 0))
od = ImageDraw.Draw(overlay)
od.ellipse([tri_cx - r, tri_cy - r, tri_cx + r, tri_cy + r], fill=(255, 255, 255, 90))
# 三角形
od.polygon([
    (tri_cx - 11, tri_cy - 17),
    (tri_cx - 11, tri_cy + 17),
    (tri_cx + 18, tri_cy),
], fill=(255, 255, 255, 255))
img = Image.alpha_composite(img, overlay)

# 重新应用圆角遮罩边缘（合成后保持透明圆角）
final = Image.new("RGBA", (S, S), (0, 0, 0, 0))
final.paste(img, (0, 0), mask)
img = final

# ---- 输出多尺寸 ico ----
sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
img.save("static/favicon.ico", format="ICO", sizes=sizes)

# 同时输出 png/svg 源供高分辨率为场景使用
img.save("static/favicon-256.png", format="PNG")
print("favicon.ico 生成完成")
