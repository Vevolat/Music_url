import re

def extract_and_update_cookie():
    input_filename = 'cookie.1.txt'
    output_filename = 'cookie.txt'
    target_appver = '8.9.75'
    
    try:
        # 1. 读取源文件
        with open(input_filename, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # 2. 提取 MUSIC_U 的值
        # 使用正则表达式匹配 MUSIC_U= 后面直到分号 ; 之前的所有内容
        match = re.search(r'MUSIC_U=(.*?);', content)
        
        if match:
            music_u_value = match.group(1)
            
            # 3. 格式化新内容
            # 按照 "MUSIC_U=获取到的内容;appver=8.9.75;" 的格式拼接
            new_cookie_content = f"MUSIC_U={music_u_value};appver={target_appver};"
            
            # 4. 写入到目标文件
            with open(output_filename, 'w', encoding='utf-8') as f:
                f.write(new_cookie_content)
            
            print(f"成功！已将提取的内容写入 '{output_filename}'。")
            print("-" * 30)
            print(new_cookie_content)
            print("-" * 30)
        else:
            print(f"错误：未在 '{input_filename}' 中找到 'MUSIC_U' 字段。")
            
    except FileNotFoundError:
        print(f"错误：找不到文件 '{input_filename}'，请确保它与脚本在同一目录下。")
    except Exception as e:
        print(f"发生未知错误：{e}")

if __name__ == '__main__':
    extract_and_update_cookie()