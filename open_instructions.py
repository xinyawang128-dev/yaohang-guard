"""Open plain-text instructions with the user's normal text editor."""
import argparse
import os
import subprocess
from pathlib import Path

ROOT=Path(__file__).resolve().parent
if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('--submission',action='store_true'); a=p.parse_args()
    path=ROOT/'submission_info.json' if a.submission else ROOT/'prompts'/'AGH完整测试指令.txt'
    print('文件：'+str(path))
    if os.name=='nt': subprocess.Popen(['notepad.exe',str(path)])
    else: print(path.read_text(encoding='utf-8-sig'))
    if a.submission:
        print('填写实际信息；文件路径使用正斜线，例如 materials/成员声明/张同学.pdf。')
        print('JSON 字符串使用英文双引号，不能删除逗号。填写后保存，再运行 06。')
    else:
        print('复制打开文件中的全部文字，粘贴到 AGH 新会话。')
        print('一次跑不完时，分别使用 prompts/01 到 04 的单用例指令。')
