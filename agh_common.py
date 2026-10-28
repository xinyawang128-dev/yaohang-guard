"""Official CLI resolution. No shell interpolation and no model credentials."""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CONFIG = ROOT / 'agh_connection.json'
SERVER_ID = 'yaohang-guard-final'


class AGHError(Exception):
    pass


def connection(cli=None, profile=None, interactive=False):
    saved = json.loads(CONFIG.read_text(encoding='utf-8')) if CONFIG.exists() else {}
    path = Path(cli or os.environ.get('AGH_CLI') or saved.get('agh_cli') or Path.home() / 'Desktop' / 'agnes-harness-main' / 'packages' / 'cli' / 'dist' / 'local' / 'agnes.mjs').expanduser()
    if not path.is_file() and interactive:
        print('默认位置未找到 AGH。请粘贴 agnes.mjs 完整路径（可以带空格）：')
        path = Path(input().strip().strip('"'))
    if not path.is_file():
        raise AGHError('找不到 AGH CLI：' + str(path) + '\n请用 --agh-cli 指定，或重新运行 02_接入AGH.bat。')
    explicit_node = os.environ.get('AGH_NODE') or saved.get('node')
    node = str(Path(explicit_node).expanduser()) if explicit_node and Path(explicit_node).expanduser().is_file() else shutil.which('node')
    if not node and os.name == 'nt':
        candidate = Path(os.environ.get('ProgramFiles', r'C:\Program Files')) / 'nodejs' / 'node.exe'
        if candidate.is_file():
            node = str(candidate)
    if not node:
        raise AGHError('找不到 Node.js；安装后重新打开终端。')
    return {'node': node, 'agh_cli': str(path.resolve()),
            'profile': profile if profile is not None else saved.get('profile'),
            'agh_home': os.environ.get('AGH_HOME', saved.get('agh_home', ''))}


def cli_command(conn, arguments):
    command = [conn['node'], conn['agh_cli']] + list(arguments)
    if conn.get('profile'):
        command += ['--profile', conn['profile']]
    return command


def run_read(conn, arguments, log=None, timeout=45):
    command = cli_command(conn, arguments)
    env = os.environ.copy()
    if conn.get('agh_home'):
        env['AGH_HOME'] = conn['agh_home']
    p = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, encoding='utf-8',
                       errors='replace', timeout=timeout, env=env)
    if log is not None:
        log.append({'command': command, 'exit_code': p.returncode, 'stdout': p.stdout, 'stderr': p.stderr})
    if p.returncode:
        raise AGHError(p.stdout + '\n' + p.stderr)
    return p.stdout


def save_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')


def configure_console():
    for stream in [sys.stdout, sys.stderr]:
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='replace')
