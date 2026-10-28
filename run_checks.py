"""One local check launcher; no AGH sessions or model calls are created."""
import subprocess
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parent
if __name__=='__main__':
    if sys.version_info < (3,10):
        print('需要 Python 3.10 或更新版本。'); raise SystemExit(1)
    print('Python：'+sys.version.split()[0]+'；路径：'+sys.executable,flush=True)
    for name in ['check_project.py','check_infrastructure.py','check_engine.py','check_web.py']:
        p=subprocess.run([sys.executable,'-X','utf8',str(ROOT/name)],cwd=ROOT)
        if p.returncode: raise SystemExit(p.returncode)
    print('\nPASS：MCP、接入／证据、独立手算与 HTTP 检查完成。各项数量见实际报告。')
    print('接下来运行 02_接入AGH.bat。本次检查未使用模型、未生成 AGH 会话。')
