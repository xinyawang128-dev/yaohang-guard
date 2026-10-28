"""Register one final server via the official CLI, retaining native trust review."""
from project_info import VERSION, EVIDENCE_SOURCES
import argparse
import datetime
import hashlib
import json
import re
import subprocess
import sys

from agh_common import ROOT, CONFIG, SERVER_ID, AGHError, connection, run_read, cli_command, save_json, configure_console
from mcp_runtime import TOOLS


def revision_from(text, server_id=SERVER_ID):
    for line in text.splitlines():
        if line.startswith(server_id + ' '):
            m = re.search(r'\brevision=([a-f0-9]{64})(?:\s|$)', line)
            if m:
                return m.group(1)
    raise AGHError('未读到最新 revision，停止修改：\n' + text)


def register(conn, log, read=None, mutate=None):
    read = read or (lambda args: run_read(conn, args, log))
    if mutate is None:
        def mutate(args):
            cmd = cli_command(conn, args)
            print('官方 CLI 若出现登记确认，请核对服务名称和本地路径后输入 y。')
            print(subprocess.list2cmdline(cmd))
            env = __import__('os').environ.copy()
            if conn.get('agh_home'):
                env['AGH_HOME'] = conn['agh_home']
            p = subprocess.run(cmd, cwd=ROOT, env=env)
            log.append({'command': cmd, 'exit_code': p.returncode, 'output': 'interactive_console'})
            if p.returncode:
                raise AGHError('服务登记失败，请保留控制台错误。')
    listing = read(['mcp', 'list'])
    ids = {line.split()[0] for line in listing.splitlines() if ' revision=' in line}
    if ('nextCursor ' in listing) or (not ids and 'No MCP servers found.' not in listing):
        raise AGHError('无法识别完整列表，未修改配置：\n' + listing)
    opts = ['--name', SERVER_ID, '--stdio', sys.executable]
    for arg in ['-u', '-X', 'utf8', str(ROOT / 'mcp_server.py'), '--database', str(ROOT / 'data' / 'tasks.sqlite3'),
                '--evidence-dir', str(ROOT / 'evidence' / 'agh' / 'tasks')]:
        opts += ['--arg', arg]
    for tool in TOOLS:
        opts += ['--allow-tool', tool['name']]
    if SERVER_ID in ids:
        revision = revision_from(read(['mcp', 'get', SERVER_ID]))
        args = ['mcp', 'update', SERVER_ID, '--expected-revision', revision] + opts
    else:
        args = ['mcp', 'add', SERVER_ID] + opts
    mutate(args)
    descriptor = read(['mcp', 'get', SERVER_ID])
    revision_from(descriptor)
    return descriptor


def local_check_current():
    files = EVIDENCE_SOURCES
    current = {n: hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in files}
    for path in sorted((ROOT/'evidence'/'local_tests').glob('project_check_*.json'), reverse=True):
        try:
            r = json.loads(path.read_text(encoding='utf-8'))
            if r.get('overall_passed') and r.get('source_sha256') == current and r.get('runtime') == {'python': sys.version, 'python_executable': sys.executable, 'platform': sys.platform}:
                return
        except (OSError, ValueError):
            pass
    if subprocess.run([sys.executable, '-X', 'utf8', str(ROOT/'check_project.py')], cwd=ROOT).returncode:
        raise AGHError('本地检查失败，未登记。')


def main():
    configure_console()
    p = argparse.ArgumentParser()
    p.add_argument('--agh-cli'); p.add_argument('--profile')
    a = p.parse_args()
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    report = {'scope': 'definition_registration_only', 'registered': False, 'agh_session_verified': False, 'commands': []}
    try:
        local_check_current()
        conn = connection(a.agh_cli, a.profile, interactive=True)
        report['descriptor'] = register(conn, report['commands'])
        report['registered'] = True
        save_json(CONFIG, conn)
        print('\n登记完成。打开 AGH 设置 → MCP，审核并启用 yaohang-guard-final。')
        print('在本项目测试期间停用旧的 yaohang 服务，避免调用错入口。')
        print('接着运行 03_检查AGH连接.bat；看到 8/8 后再运行测试指令。')
    except (Exception, KeyboardInterrupt) as exc:
        report['error'] = str(exc) or '已中止'
        print('登记未完成：' + report['error'])
    out = ROOT / 'evidence' / 'agh' / 'setup' / ('register_' + stamp + '.json')
    save_json(out, report)
    print('记录：' + str(out))
    return 0 if report['registered'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
