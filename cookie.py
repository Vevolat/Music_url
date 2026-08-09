"""Cookie 提取工具

功能:
1. 自动检测当前目录是否存在 cookie.1.txt，若不存在则用内置默认 Cookie 创建
2. 从 cookie.1.txt 中提取 MUSIC_U 字段，按 "MUSIC_U=xxx;appver=8.9.75;" 格式写入 cookie.txt

用法:
    python cookie.py
"""

import re
from pathlib import Path

# ============ 默认 Cookie（当 cookie.1.txt 不存在时自动创建） ============
DEFAULT_COOKIE = (
    "_ga=GA1.1.1467317620.1782813292; "
    "_ntes_nnid=0ef1dbccbaac2aaf6e3f1d8057d59534,1783735427153; "
    "_ntes_nuid=0ef1dbccbaac2aaf6e3f1d8057d59534; "
    "NMTID=00O2UQwhAHlL1KOpkxQudZdSJPTNXkAAAGfTuqeMQ; "
    "WEVNSM=1.0.0; "
    "WNMCID=zvgupw.1783735427569.01.0; "
    "__snaker__id=GjsCCzpp12x1x5ES; "
    "WM_TID=nb27ZxQQ8oxFRAUQQFeC%2FnGpuY2NORns; "
    "ntes_utid=tid._.%252B025bHXgcLlEU0QEREfG%252BjD5qdzdwUnU._.0; "
    "sDeviceId=YD-Yp6WjGqW8RFAV0BVVBPSujW8%2FY3Z1A2U; "
    "ntes_kaola_ad=1; "
    "_iuqxldmzr_=32; "
    "timing_user_id=time_aRp6Rl5V98; "
    "_ga_EPDQHDTJH5=GS2.1.s1785756275$o5$g0$t1785756420$j60$l0$h0; "
    "WM_NI=%2FYRTWalQgV9FQRkS4%2BGuUfHnjErBbM%2FBlgpaJ2Iasc%2F9n0Su1SJDsnt4zpo%2BG3b8BOqfH4OKq0q9sQwloXDsacQIHcOikcvxr0YcRapFAAMk3Eb%2BWrjTpewEZ%2FzUaWGZMm4%3D; "
    "WM_NIKE=9ca17ae2e6ffcda170e2e6eeaef25bb6f08b8ee563e9eb8ea6c45e928e8ab0d625eda8fdd7ed7091aaf986cf2af0fea7c3b92aed879eb5d66bb08fa9b7bc4e938ea5b4b72185ab9b87cb66aa9bbea3e147ed9ea488f36b8aee8782f269ede7a2d1d27ff38d86a5f266b8ecb691ee2185edaed9c145b3ba88d5ce41b3f0bfdaf25bb5b4a1b9c779a3bd9faacb698db7a584f574b2f09784d16bb49a8fa2d061f19baeccd67aaa8cc086f64f9af1b6b6e45d8586838eb737e2a3; "
    "JSESSIONID-WYYY=EeN42fsNUXXmo3UySKcOx4MuXasAu8Xd6trPn2VubYY8Ut4qdp9k9CvJjoNHYOlv6NCmNssN6jWAq%2FtikOmIoe2pfn%5C%5Ca%5CaqYhTmcVB2m74VYfxq9uDW%2BNoDNP%2F0XWg3NK6%5Cf6k6vUNWXZC%2F%5CnH3ZxaMdu1RjeUT0XcAXdw8v47XgHSJ%3A1786284315499; "
    "Hm_lvt_1483fb4774c02a30ffa6f0e2945e9b70=1785601725,1786181234,1786269206,1786282516; "
    "HMACCOUNT=804DF5CC6820791F; "
    "gdxidpyhxdE=9NsP%2BfXpLlxk%5C8T7SAJvhBz7mvDaxM9EvcDJ5ZC7HEQm2d9lgWHb3P%2FJimm19Oc8ujpLOpYILn3WJJIKaakKJinTdpOKhxtYP5oiclJMdIQOmfWPMyDggf42KsIVibiyrSGMWJXmsuX5dG%2BYvCL6Kt7MJmKNPHmfdBozr6hxmZniZK7b%3A1786283428610; "
    "Hm_lpvt_1483fb4774c02a30ffa6f0e2945e9b70=1786283292"
)

INPUT_FILENAME = "cookie.1.txt"
OUTPUT_FILENAME = "cookie.txt"
TARGET_APPVER = "8.9.75"


def ensure_cookie_source(input_filename: str = INPUT_FILENAME) -> None:
    """检测 cookie.1.txt 是否存在，不存在则用默认 Cookie 创建"""
    path = Path(input_filename)
    if path.exists():
        print(f"✓ 检测到 '{input_filename}'，使用现有文件。")
        return
    print(f"未找到 '{input_filename}'，自动创建并写入默认 Cookie...")
    path.write_text(DEFAULT_COOKIE.strip() + "\n", encoding="utf-8")
    print(f"✓ 已创建 '{input_filename}'。")


def extract_and_update_cookie():
    """从 cookie.1.txt 提取 MUSIC_U 并写入 cookie.txt"""
    input_filename = INPUT_FILENAME
    output_filename = OUTPUT_FILENAME
    target_appver = TARGET_APPVER

    # 1. 确保源文件存在（不存在则用默认 Cookie 创建）
    ensure_cookie_source(input_filename)

    try:
        # 2. 读取源文件
        with open(input_filename, "r", encoding="utf-8") as f:
            content = f.read()

        # 3. 提取 MUSIC_U 的值
        # 使用正则表达式匹配 MUSIC_U= 后面直到分号 ; 之前的所有内容
        match = re.search(r"MUSIC_U=(.*?);", content)

        if match:
            music_u_value = match.group(1)

            # 4. 格式化新内容
            # 按照 "MUSIC_U=获取到的内容;appver=8.9.75;" 的格式拼接
            new_cookie_content = f"MUSIC_U={music_u_value};appver={target_appver};"

            # 5. 写入到目标文件
            with open(output_filename, "w", encoding="utf-8") as f:
                f.write(new_cookie_content)

            print(f"✓ 成功！已将提取的内容写入 '{output_filename}'。")
            print("-" * 30)
            print(new_cookie_content)
            print("-" * 30)
        else:
            print(f"✗ 错误：未在 '{input_filename}' 中找到 'MUSIC_U' 字段。")
            print("提示：内置默认 Cookie 不含 MUSIC_U（账号登录凭证）。")
            print("请登录网易云音乐网页版 → F12 开发者工具 → Network 标签页，")
            print("复制请求头中的完整 Cookie 覆盖到该文件后，重新运行本脚本。")

    except FileNotFoundError:
        print(f"✗ 错误：找不到文件 '{input_filename}'，请确保它与脚本在同一目录下。")
    except Exception as e:
        print(f"✗ 发生未知错误：{e}")


if __name__ == "__main__":
    extract_and_update_cookie()
