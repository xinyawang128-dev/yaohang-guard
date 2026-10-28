"""Read AGH's observed status and catalog; never infer a model execution."""
import argparse
import datetime
import re
from agh_common import ROOT, SERVER_ID, connection, run_read, save_json, configure_console
from mcp_runtime import TOOLS


def inspect(conn, log, read=None):
    read = read or (lambda args: run_read(conn, args, log))
    descriptor = read(['mcp', 'get', SERVER_ID])
    status = read(['mcp', 'status', SERVER_ID])
    catalog = read(['mcp', 'tools', SERVER_ID])
    names = {line.split(' — ', 1)[0].strip() for line in catalog.splitlines() if line.strip()}
    expected = {t['name'] for t in TOOLS}
    ready = bool(re.search(r'\bconnection=ready(?:\s|$)', status))
    revisions = re.search(r'\brevision=([a-f0-9]{64})', descriptor)
    observed = re.search(r'\brevision=([a-f0-9]{64})', status)
    same = bool(revisions and observed and revisions.group(1) == observed.group(1))
    catalog_revision = re.search(r'\bcatalog=([a-f0-9]{64})', status)
    catalog_current = bool(revisions and catalog_revision and revisions.group(1) == catalog_revision.group(1))
    return {'descriptor': descriptor, 'status': status, 'catalog': catalog,
            'expected': sorted(expected), 'missing': sorted(expected-names),
            'unexpected': sorted(names-expected), 'connection_ready': ready, 'current_revision_observed': same,
            'catalog_revision_current': catalog_current,
            'catalog_ready': ready and same and catalog_current and names == expected,
            'model_execution_verified': False}


def main():
    configure_console()
    p = argparse.ArgumentParser(); p.add_argument('--agh-cli'); p.add_argument('--profile'); a = p.parse_args()
    r = {'catalog_ready': False, 'commands': [], 'model_execution_verified': False}
    try:
        r.update(inspect(connection(a.agh_cli, a.profile), r['commands']))
        print(r['descriptor']); print(r['status'])
        print('工具发现：' + str(8-len(r['missing'])) + '/8')
        if r['catalog_ready']:
            print('PASS：当前服务连接就绪，8 个工具均已发现。下一步在 AGH 中执行测试指令。')
        else:
            print('未就绪。请在设置 → MCP 完成审核、启用；结束当前轮或新开会话后重试。')
            print('缺失工具：' + str(r['missing']))
            print('若 AGH Web 使用其他 profile 或 AGH_HOME，请按 README 指定相同配置。')
    except Exception as exc:
        r['error'] = str(exc); print('检查失败：' + str(exc))
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    save_json(ROOT/'evidence'/'agh'/'setup'/('catalog_'+stamp+'.json'), r)
    return 0 if r['catalog_ready'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
