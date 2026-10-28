"""Export actual user-selected AGH sessions using the documented native CLI."""
import argparse
import datetime
import hashlib
from agh_common import ROOT, connection, run_read, save_json, configure_console
from agh_evidence import read_ledger


def main():
    configure_console()
    p = argparse.ArgumentParser(); p.add_argument('session_id', nargs='?'); p.add_argument('--agh-cli'); p.add_argument('--profile')
    a = p.parse_args(); log = []
    try:
        conn = connection(a.agh_cli, a.profile)
        sid = a.session_id
        if not sid:
            print('以下是当前配置中的 AGH 会话列表：')
            print(run_read(conn, ['sessions', '--json'], log))
            print('\n输入刚完成测试的 AGH 会话 ID；不要填写 create_task 返回的 12 位任务 ID：')
            sid = input().strip()
        if not sid or len(sid)>512 or sid.startswith('-') or any(ord(c)<32 for c in sid):
            raise ValueError('会话 ID 无效。')
        stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        stem = stamp + '_' + hashlib.sha256(sid.encode()).hexdigest()[:12]
        folder = ROOT/'evidence'/'agh'/'sessions'; folder.mkdir(parents=True, exist_ok=True)
        native, html = folder/(stem+'.jsonl'), folder/(stem+'.html')
        print(run_read(conn, ['export', sid, '--format', 'agnes', '-o', str(native)], log, timeout=90))
        if not native.is_file() or not native.stat().st_size:
            raise ValueError('AGH CLI 未生成会话文件。')
        inspection = read_ledger(native)
        report = {k:v for k,v in inspection.items() if k != 'calls'}
        report['requested_session_id'] = sid; report['commands'] = log
        report['session_id_matches'] = inspection.get('session_id') == sid
        try:
            print(run_read(conn, ['export', sid, '--html', '-o', str(html)], log, timeout=90))
            if not html.is_file() or not html.stat().st_size: raise ValueError('CLI 未生成非空 HTML 文件。')
            report['html_file'] = str(html)
        except Exception as exc:
            report['html_error'] = str(exc)
            print('原生 JSONL 已保存；HTML 导出失败：' + str(exc))
        save_json(folder/(stem+'_index.json'), report)
        print('AGH 原生会话：' + str(native))
        if inspection.get('error'):
            print('已保存，但自动识别未通过：' + inspection['error'] + '\n请保留原文件并人工核查。')
        elif not report['session_id_matches']:
            print('已保存，但会话 ID 与请求不一致；请核对 profile 和原始会话。')
        else:
            print('已识别原生事件结构。下一步运行 06_整理比赛数据.bat。')
        print('如果测试分在多个会话，重复导出每一个会话。')
        return 0 if not inspection.get('error') and report['session_id_matches'] else 2
    except (Exception, KeyboardInterrupt) as exc:
        print('会话导出失败：' + (str(exc) or '已中止'))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
