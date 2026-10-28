"""Match native AGH ledger events to MCP exports. Structure is not a signature."""
import datetime
import hashlib
import json
import re
from pathlib import Path
from engine import canonical_json
from mcp_runtime import TOOLS

NAMES = {t['name'] for t in TOOLS}
ULID = re.compile(r'^[0-9A-HJKMNP-TV-Z]{26}$')

def agnes_name(value):
    return isinstance(value, str) and bool(re.search(r'(^|[/.:])agnes(?:[-_./:]|$)', value.strip(), re.I))


def payloads(data):
    """Official tool/result content or structured data; unwrap MCP text once."""
    out = []
    if isinstance(data, dict):
        if isinstance(data.get('structured'), dict):
            out.append(data['structured'])
        for block in data.get('content', []):
            if isinstance(block, dict) and block.get('type') == 'text':
                try:
                    value = json.loads(block['text'])
                    if isinstance(value, dict):
                        out.append(value)
                        if 'content' in value:
                            out.extend(payloads(value))
                except (ValueError, KeyError, TypeError):
                    pass
    return out


def decode_call(data):
    name, args = data.get('name', ''), data.get('args')
    if name in NAMES:
        return name, args
    for tool in NAMES:
        # Harness versions may use a readable service prefix or an opaque prefix.
        # Full arguments, results, task ID and exported digest are matched later.
        if name.endswith('_' + tool):
            return tool, args
    # Older AGH may expose a generic MCP wrapper instead of a namespaced tool.
    if isinstance(args, dict):
        server = args.get('serverId', args.get('server_id', args.get('server')))
        tool = args.get('toolName', args.get('tool_name', args.get('tool', args.get('name'))))
        if server == 'yaohang-guard-final' and tool in NAMES:
            return tool, args.get('arguments', args.get('args'))
    return None, None


def read_ledger(path):
    out = {'file': str(path), 'recognized_native_structure': False, 'authenticity_verified': False,
           'calls': [], 'models': [], 'non_agnes_models': [],
           'unknown_model_requests': 0, 'all_session_models_agnes': False, 'error': None}
    try:
        data = Path(path).read_bytes()
        if len(data) > 80*1024*1024:
            raise ValueError('会话文件过大，请另存并人工审核。')
        events = [json.loads(line) for line in data.decode('utf-8-sig').splitlines() if line.strip()]
        if not events or events[0].get('type') != 'session/start':
            raise ValueError('需要完整的官方 --format agnes JSONL；首条应为 session/start。')
        ids, prev = set(), 0
        for e in events:
            if not isinstance(e, dict) or not {'seq','ts','id','type','data','actor','origin','trust'} <= set(e):
                raise ValueError('文件不是支持的原生事件结构。')
            if not isinstance(e['seq'], int) or e['seq'] <= prev or not isinstance(e['id'], str) or not ULID.fullmatch(e['id']) or e['id'] in ids:
                raise ValueError('事件编号、顺序或标识异常。')
            datetime.datetime.fromisoformat(e['ts'].replace('Z', '+00:00'))
            if not isinstance(e['actor'], dict) or not {'id','org','role','deptPath','attrs'} <= set(e['actor']):
                raise ValueError('缺少原生 actor 结构。')
            prev = e['seq']; ids.add(e['id'])
        start = events[0]['data']
        if not isinstance(start, dict) or not {'key','agnesVersion'} <= set(start) or start.get('imported'):
            raise ValueError('缺少原生会话信息，或这是导入会话；需人工核查原始来源。')
        out.update(recognized_native_structure=True, session_id=start['key'],
                   agh_version=start['agnesVersion'], file_sha256=hashlib.sha256(data).hexdigest(), event_count=len(events))
        calls, model, models = {}, None, set()
        for e in events:
            value = e['data']
            if not isinstance(value, dict):
                continue
            if e['type'] == 'step/start':
                model = None
            if e['type'] == 'request/header' and isinstance(value.get('model'), str):
                model = value['model']; models.add(model)
            if e['type'] == 'request/sent' and isinstance(value.get('model'), dict):
                candidate = value['model'].get('responseModel') or value['model'].get('id')
                if isinstance(candidate, str):
                    model = candidate; models.add(model)
            if e['type'] == 'request/sent' and not isinstance(model, str):
                out['unknown_model_requests'] += 1
            if e['type'] == 'tool/call' and e['origin'] == 'model':
                name, args = decode_call(value)
                if name and isinstance(args, dict) and isinstance(value.get('toolUseId'), str):
                    calls[value['toolUseId']] = {'name': name, 'arguments': args, 'model': model,
                                                 'call_seq': e['seq'], 'utc': e['ts']}
            if e['type'] == 'tool/result' and value.get('toolUseId') in calls and value.get('isError') is False:
                call = calls.pop(value['toolUseId'])
                call.update(result_seq=e['seq'], payloads=payloads(value))
                out['calls'].append(call)
        out['models'] = sorted(models)
        out['non_agnes_models'] = sorted(m for m in models if not agnes_name(m))
        out['all_session_models_agnes'] = bool(models) and not out['non_agnes_models'] and not out['unknown_model_requests']
    except (OSError, ValueError, TypeError, AttributeError, KeyError) as exc:
        out['error'] = str(exc)
    return out


def same(left, right):
    try:
        return canonical_json(left) == canonical_json(right)
    except (ValueError, TypeError):
        return False


def match_task(report, ledgers):
    needed = report.get('tool_rpc_trace', [])
    for ledger in ledgers:
        if not ledger['recognized_native_structure'] or ledger.get('error'):
            continue
        calls, cursor, matched = ledger['calls'], 0, []
        for rpc in needed:
            found = None
            for i in range(cursor, len(calls)):
                c = calls[i]
                if c['name'] == rpc['tool'] and same(c['arguments'], rpc['arguments']) and any(same(p, rpc['result']) for p in c['payloads']):
                    found = i; break
            if found is None:
                break
            matched.append(calls[found]); cursor = found+1
        else:
            export = next((c for c in calls[cursor:] if c['name'] == 'export_evidence' and c['arguments'].get('task_id') == report['task_id'] and
                           any(p.get('sha256') == report['sha256'] for p in c['payloads'])), None)
            if export:
                matched.append(export)
                models = sorted({c['model'] for c in matched if isinstance(c['model'], str)})
                agnes = all(agnes_name(c['model']) for c in matched)
                return {'native_tool_chain_matched': True, 'agnes_core_calls_observed': agnes,
                        'all_session_models_agnes': ledger['all_session_models_agnes'],
                        'session_models': ledger['models'], 'non_agnes_models': ledger['non_agnes_models'],
                        'unknown_model_requests': ledger['unknown_model_requests'],
                        'models': models, 'session_id': ledger['session_id'], 'ledger_file': ledger['file'],
                        'matched_calls': len(matched), 'authenticity_verified': False,
                        'review_note': '仅匹配原生结构、实际参数及结果；真实性和参赛资格仍须人工审核。'}
    return {'native_tool_chain_matched': False, 'agnes_core_calls_observed': False,
            'all_session_models_agnes': False,
            'authenticity_verified': False, 'review_note': '未找到对应完整调用链；请导出执行这些任务的 AGH 会话。'}
