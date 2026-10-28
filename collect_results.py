"""Collect actual MCP task exports, match AGH ledgers, list missing materials."""
from project_info import VERSION, EVIDENCE_SOURCES
import argparse
import csv
import datetime
import hashlib
import json
import re
import zipfile
from pathlib import Path
from urllib.parse import urlparse

from engine import verify_report
from cases import REQUIRED, OPTIONAL, TITLES, check_case
from agh_evidence import read_ledger, match_task, agnes_name
from agh_common import ROOT, save_json, configure_console

SOURCE = EVIDENCE_SOURCES

def evidence_ready(item):
    a = item['agh']
    return a.get('native_tool_chain_matched') and a.get('agnes_core_calls_observed') and a.get('all_session_models_agnes')


def inspect_reports(folder, code_root=ROOT):
    current = {n: hashlib.sha256((code_root/n).read_bytes()).hexdigest() for n in SOURCE}
    out = []
    for path in sorted(Path(folder).glob('mcp_*.json')):
        item = {'file': str(path), 'valid': False, 'errors': []}
        try:
            r = json.loads(path.read_text(encoding='utf-8-sig'))
            item.update(task_id=r.get('task_id'), case_id=r.get('case_id'), payload=r)
            if not verify_report(r):
                item['errors'].append('内容 SHA256 不匹配，文件可能已修改。')
            if r.get('project_version') != VERSION or r.get('source_sha256') != current:
                item['errors'].append('导出代码与当前最终版不一致，请用当前工程重新测试。')
            if not isinstance(r.get('task_id'), str) or not re.fullmatch('[a-f0-9]{12}', r['task_id']):
                item['errors'].append('项目任务 ID 异常。')
            item['errors'] += check_case(r)
            item['valid'] = not item['errors']
        except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
            item['errors'].append('无法读取有效证据：' + str(exc))
        out.append(item)
    return out


def collect(code_root=ROOT, tasks=None, sessions=None):
    tasks = tasks or code_root/'evidence'/'agh'/'tasks'
    sessions = sessions or code_root/'evidence'/'agh'/'sessions'
    ledgers = [read_ledger(p) for p in sorted(Path(sessions).glob('*.jsonl'))]
    items = inspect_reports(tasks, code_root)
    for item in items:
        item['agh'] = match_task(item['payload'], ledgers) if item['valid'] else {'native_tool_chain_matched': False, 'agnes_core_calls_observed': False}
    selected = {}
    for case in REQUIRED + OPTIONAL:
        candidates = [i for i in items if i.get('case_id') == case and i['valid']]
        candidates.sort(key=lambda i: (bool(evidence_ready(i)), i['file']), reverse=True)
        if candidates:
            selected[case] = candidates[0]
    missing = [c for c in REQUIRED if c not in selected]
    pending = [c for c in REQUIRED if c in selected and not evidence_ready(selected[c])]
    return {'required_cases': REQUIRED, 'missing_cases': missing, 'pending_agh_cases': pending,
            'engineering_cases_complete': not missing,
            'native_agh_evidence_observed': not missing and not pending,
            'authenticity_verified': False, 'manual_review_required': True,
            'selected': selected, 'all_tasks': items,
            'ledgers': [{k:v for k,v in ledger.items() if k != 'calls'} for ledger in ledgers]}


def url_ok(value):
    if not isinstance(value, str):
        return False
    try:
        parsed = urlparse(value)
        return parsed.scheme in ['https','http'] and bool(parsed.hostname)
    except ValueError:
        return False

def filled(value):
    return isinstance(value, str) and bool(value.strip())

def publication_date(value):
    try:
        date = datetime.date.fromisoformat(value)
        today = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).date()
        return date <= today
    except (ValueError, TypeError):
        return False


def project_file(value, code_root):
    if not isinstance(value, str) or not value.strip():
        return False
    path = (code_root/value).resolve()
    return path.is_relative_to(code_root.resolve()) and path.is_file() and path.stat().st_size > 0


def missing_materials(info, code_root=ROOT):
    missing = []
    for key, label in [('group','组别'),('registration_id','参赛编号'),('team_name','队伍名称'),
                       ('leader_name','队长姓名'),('school','学校')]:
        if not isinstance(info.get(key), str) or not info[key].strip():
            missing.append(label)
    if info.get('group') and info['group'] not in ['本科生组','硕博组']:
        missing.append('组别须填写本科生组或硕博组')
    video = info.get('video', {})
    video = video if isinstance(video, dict) else {}
    if not url_ok(video.get('url')) or not isinstance(video.get('duration_seconds'), (int,float)) or not 180 <= video['duration_seconds'] <= 300:
        missing.append('3–5 分钟演示视频的链接和实际时长')
    posts = info.get('public_posts', [])
    posts = posts if isinstance(posts, list) else []
    if not any(isinstance(p,dict) and filled(p.get('platform')) and url_ok(p.get('url')) and publication_date(p.get('published_date')) and project_file(p.get('screenshot_file'), code_root) for p in posts):
        missing.append('至少一条公开作品内容的平台、链接、真实发布日期和截图文件')
    members = info.get('members', [])
    members = members if isinstance(members, list) else []
    if not 1 <= len(members) <= 3 or not all(isinstance(m,dict) and filled(m.get('name')) and filled(m.get('role')) and project_file(m.get('signed_statement_file'), code_root) for m in members):
        missing.append('每位成员的姓名、分工和本人声明文件')
    elif len({m['name'].strip() for m in members}) != len(members):
        missing.append('成员姓名重复，请核对真实成员名单')
    models = info.get('models_used', [])
    models = models if isinstance(models, list) else []
    if not models or not all(isinstance(m,dict) and all(filled(m.get(k)) for k in ['name','version','stage','method']) for m in models):
        missing.append('实际使用模型的名称、版本、阶段与调用方式')
    elif any(not agnes_name(m['name']) for m in models):
        missing.append('作品运行模型须仅为 Agnes；开发辅助工具请在使用披露中如实说明')
    if not filled(info.get('development_ai_disclosure')):
        missing.append('代码开发中 AI 工具的使用披露')
    if not any(p.is_file() and p.stat().st_size for p in (code_root/'docs').glob('项目说明.*') if p.suffix.lower() in ['.pdf','.doc','.docx','.ppt','.pptx']):
        missing.append('可上传的项目说明 PDF/Word/PPT 文件')
    return missing

def material_limits(code_root):
    errors=[]
    images=list((code_root/'materials').rglob('*'))
    images=[p for p in images if p.is_file() and p.suffix.lower() in ['.png','.jpg','.jpeg','.webp','.gif']]
    if len(images)>20: errors.append('材料图片超过 20 张')
    for p in images:
        if p.stat().st_size>10*1024*1024: errors.append(str(p.relative_to(code_root))+'：图片超过 10 MB')
    for p in (code_root/'docs').rglob('*'):
        if p.is_file() and p.suffix.lower() in ['.pdf','.doc','.docx','.ppt','.pptx'] and p.stat().st_size>50*1024*1024:
            errors.append(str(p.relative_to(code_root))+'：文档超过 50 MB')
    return errors


def metrics(item):
    r, a = item['payload'], item['agh']; v = r['verification']; c = r['initial_config']
    history = r.get('history', []) or [{'temperature_c': c['initial_c']}]
    selected = r.get('initial_selected') or {}; nominal = selected.get('nominal', {}); robust = selected.get('robust', {})
    baseline = (r.get('baseline_shortest_standard') or {}).get('nominal', {})
    rpc = r['tool_rpc_trace']; paths = [x['arguments']['route'][:2] for x in rpc if x['tool']=='execute_step']
    route = '-'.join([paths[0][0]]+[p[1] for p in paths]) if paths else 'A'
    mc = r.get('monte_carlo_initial') or {}
    return {'用例': TITLES[r['case_id']], 'case_id': r['case_id'], '任务ID': r['task_id'], '结果': v['status'],
            '测试判定': 'PASS', '执行航线': route, '包装': r.get('pack') or '未起飞',
            '时间_min': v['time_min'], '时限_min': c['deadline_min'], '能耗_Wh': v['energy_wh'],
            '剩余电量_Wh': c['battery_wh']-v['energy_wh'], '预留电量_Wh': c['reserve_wh'],
            '仿真终点温度_C': v['temperature_c'], '仿真峰值温度_C': max(p['temperature_c'] for p in history),
            '仿真最低温度_C': min(p['temperature_c'] for p in history), '传感器正常': v['sensor_ok'],
            '故障事件数': sum(x['tool']=='inject_event' for x in rpc), '实际规划调用数': sum(x['tool']=='plan_candidates' for x in rpc),
            '初始方案最坏时间_min': robust.get('time_max_min'), '初始方案最坏能耗_Wh': robust.get('energy_max_wh'),
            '初始方案最坏峰值_C': robust.get('peak_max_c'), '初始方案不确定性角点数': robust.get('corners'),
            '最短路线标准包装峰值_C': baseline.get('peak_c'), '初始方案名义峰值_C': nominal.get('peak_c'),
            '初始方案MonteCarlo样本数': mc.get('samples'), '初始方案MonteCarlo失败数': mc.get('failures'),
            'AGH原生调用链匹配': a['native_tool_chain_matched'], 'Agnes调用观察到': a['agnes_core_calls_observed'],
            '整个会话模型仅限Agnes': a.get('all_session_models_agnes',False),
            'AGH会话ID': a.get('session_id',''), '实际模型': ';'.join(a.get('models',[])), '证据SHA256': r['sha256'],
            '数据性质': '合成仿真；非硬件实测'}


def package_name(info, ready):
    if not ready:
        return '药航守护_提交草稿.zip'
    values = [info[k].strip() for k in ['group','registration_id','team_name','leader_name']]
    if any(re.search(r'[<>:"/\\|?*\x00-\x1f]', v) or v.endswith(('.', ' ')) for v in values):
        raise ValueError('提交信息包含 Windows 文件名不允许的字符。')
    return '-'.join(values)+'.zip'


def build_zip(code_root, out, name):
    path = out/name
    excluded = {'__pycache__','.git','data','node_modules','submission'}
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
        for p in sorted(code_root.rglob('*')):
            rel = p.relative_to(code_root)
            if not p.is_file() or p.is_symlink() or any(part in excluded for part in rel.parts) or p.suffix in ['.pyc','.sqlite3','.tmp','.zip','.pem','.key'] or p.name in ['agh_connection.json','.env'] or p.name.startswith('.env.'):
                continue
            # Only actual AGH evidence goes into the contest draft; local QA stays separate.
            if rel.parts[0] == 'evidence' and (len(rel.parts)<2 or rel.parts[1] != 'agh'):
                continue
            z.write(p, 'yaohang_guard_agh_final/'+str(rel))
        for p in sorted(out.iterdir()):
            if p.is_file() and p.suffix in ['.csv','.json','.md','.txt']:
                z.write(p, '比赛结果/'+p.name)
    return path


def main():
    configure_console()
    parser = argparse.ArgumentParser(); parser.add_argument('--no-zip', action='store_true'); args = parser.parse_args()
    out = ROOT/'submission'; out.mkdir(exist_ok=True)
    report = collect()
    try:
        info = json.loads((ROOT/'submission_info.json').read_text(encoding='utf-8-sig'))
        if not isinstance(info,dict): raise ValueError('提交信息必须为 JSON 对象')
    except (OSError, ValueError) as exc:
        info = {}; report['submission_info_error'] = str(exc)
    report['missing_materials'] = missing_materials(info) + material_limits(ROOT)
    declared={m['version'].strip() for m in info.get('models_used',[]) if isinstance(m,dict) and filled(m.get('version'))} if isinstance(info.get('models_used'),list) else set()
    observed={model for item in report['selected'].values() for model in item['agh'].get('models',[])}
    if observed and not observed <= declared:
        report['missing_materials'].append('模型版本与原生会话不一致；实际记录：'+', '.join(sorted(observed)))
    report['automatic_precheck_passed'] = report['native_agh_evidence_observed'] and not report['missing_materials']
    report['official_acceptance_verified'] = False
    report['generated_utc'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    rows = [metrics(report['selected'][case]) for case in REQUIRED+OPTIONAL if case in report['selected']]
    csv_file = out/'比赛测试数据.csv'
    with csv_file.open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]) if rows else ['用例','结果','数据性质'])
        writer.writeheader(); writer.writerows(rows)
    lines = ['# 药航守护：比赛数据与提交检查', '', '自动检查：' + ('通过，仍须人工审核材料和真实性。' if report['automatic_precheck_passed'] else '尚未完成，请补齐下列项目。'), '',
             '所有温度、时间和能耗均为合成仿真数值；Monte Carlo 只评估初始静态方案。', '',
             '| 用例 | 工程测试 | AGH 原生调用链／Agnes |', '|---|---|---|']
    for case in REQUIRED+OPTIONAL:
        item = report['selected'].get(case)
        lines.append('| '+TITLES[case]+' | '+('PASS' if item else '缺少比赛用任务导出')+' | '+('已匹配，整个会话模型记录通过检查' if item and evidence_ready(item) else '待提供或模型记录不符合')+' |')
    lines += ['', '## 待补齐', '']
    missing = [TITLES[c]+'：比赛用任务导出（需在 AGH 中实际运行）' for c in report['missing_cases']] + [TITLES[c]+'：AGH 会话与 Agnes 记录' for c in report['pending_agh_cases']] + report['missing_materials']
    lines += ['- '+s for s in missing] or ['- 自动检查未发现缺项；人工检查视频／公开链接可访问、声明属实、专业结论与仿真范围一致。']
    lines += ['', '## 无效证据', '']
    bad = [i for i in report['all_tasks'] if not i['valid']]
    lines += ['- '+Path(i['file']).name+'：'+'；'.join(i['errors']) for i in bad] or ['- 未发现。']
    lines += ['', '## 会话来源核查', '', '自动匹配只说明文件结构、参数、结果和模型元数据相符。SHA256 用于检查内容完整性，不能证明作者身份、模型身份或评委认可。',
              '若旧 AGH 的事件格式未被识别，请保留原生 JSONL／HTML 并人工核对痕迹；不能把本机报告改名充当会话。']
    (out/'比赛测试报告.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    save_json(out/'证据检查.json', {k:v for k,v in report.items() if k not in ['selected','all_tasks']} | {
        'tasks': [{k:v for k,v in i.items() if k != 'payload'} for i in report['all_tasks']]})
    print('已生成：'+str(csv_file)); print('报告：'+str(out/'比赛测试报告.md'))
    for m in missing: print('待补齐：'+m)
    if not args.no_zip:
        z = build_zip(ROOT, out, package_name(info, report['automatic_precheck_passed']))
        print('整理包：'+str(z))
        if z.stat().st_size > 200*1024*1024:
            print('当前包超过 200 MB，请按赛事要求改用仓库或共享链接。')
    print('需人工检查视频、公开链接、成员声明和 AGH 原始痕迹后，再向赛事提交。')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
