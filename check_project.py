"""Real stdio subprocess checks. No model key or AGH session is used."""
from project_info import VERSION, EVIDENCE_SOURCES
import datetime
import hashlib
import json
import queue
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from mcp_runtime import TOOLS
ROOT = Path(__file__).resolve().parent
class CheckError(Exception):
    pass
def require(condition, message):
    if not condition:
        raise CheckError(message)

class SingleMCP:
    def __init__(self, trace, entry, database, evidence):
        self.trace = trace
        self.entry = entry
        self.seq = 0
        self.lines = queue.Queue()
        self.err = tempfile.TemporaryFile(mode='w+t', encoding='utf-8')
        self.proc = subprocess.Popen(
            [sys.executable, '-u', '-X', 'utf8', str(ROOT / entry), '--database', str(database), '--evidence-dir', str(evidence)],
            cwd=str(ROOT), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=self.err, text=True, encoding='utf-8',
        )
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        try:
            for line in self.proc.stdout:
                self.lines.put(line)
        finally:
            self.lines.put(None)

    def rpc(self, method, params=None):
        self.seq += 1
        request = {'jsonrpc': '2.0', 'id': self.seq, 'method': method}
        if params is not None:
            request['params'] = params
        entry = {'service': self.entry, 'request': request}
        self.trace.append(entry)
        self.proc.stdin.write(json.dumps(request, ensure_ascii=False) + '\n')
        self.proc.stdin.flush()
        deadline = time.monotonic() + 20
        while True:
            try:
                line = self.lines.get(timeout=max(0.01, deadline - time.monotonic()))
            except queue.Empty:
                raise CheckError('MCP 响应超时，请检查 mcp_server.py 是否为 stdio 服务。')
            if line is None:
                self.err.seek(0)
                raise CheckError('MCP 进程已退出：' + self.err.read()[-2000:])
            try:
                response = json.loads(line)
            except json.JSONDecodeError:
                raise CheckError('服务 stdout 出现非 JSON 内容：' + line[:200])
            if 'id' not in response:
                continue
            require(response.get('id') == self.seq, 'MCP 响应编号不匹配。')
            entry['response'] = response
            require('error' not in response, 'MCP 协议错误：' + str(response.get('error')))
            return response['result']

    def call(self, name, arguments, expect_error=False):
        result = self.rpc('tools/call', {'name': name, 'arguments': arguments})
        content = '\n'.join(c.get('text', '') for c in result.get('content', []) if c.get('type') == 'text')
        if expect_error:
            require(result.get('isError') is True, name + ' 应拒绝执行但未返回错误。')
            return content
        require(not result.get('isError'), name + ' 返回错误：' + content)
        return json.loads(content)

    def close(self):
        if self.proc.stdin:
            self.proc.stdin.close()
        try:
            self.proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait(timeout=3)
        self.proc.stdout.close()
        self.err.close()



class MCP:
    def __init__(self, trace):
        self.trace = trace
        self.temp = tempfile.TemporaryDirectory(prefix='yaohang_final_check_')
        self.database = Path(self.temp.name) / 'tasks.sqlite3'
        self.evidence = Path(self.temp.name) / 'evidence'
        self.saved_evidence = ROOT / 'evidence' / 'local_tests' / datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        self.server = None
        self.restart()

    def restart(self):
        if self.server is not None:
            self.server.close()
        self.server = SingleMCP(self.trace, 'mcp_server.py', self.database, self.evidence)
        self.servers = self.server.rpc('initialize', {
            'protocolVersion': '2025-03-26', 'capabilities': {},
            'clientInfo': {'name': 'yaohang-local-check', 'version': VERSION},
        })['serverInfo']
        self.catalogs = self.server.rpc('tools/list')['tools']
        require([t['name'] for t in self.catalogs] == [t['name'] for t in TOOLS], '必须在一个服务中列出全部 8 个工具。')
        require(self.servers['name'] == 'yaohang-guard-final', '服务名称不正确。')

    def call(self, name, arguments, expect_error=False):
        return self.server.call(name, arguments, expect_error)

    def close(self):
        if self.server is not None:
            self.server.close()
        self.temp.cleanup()


def create(client, config=None, case_id='custom'):
    return client.call('create_task', {'config': config or {}, 'case_id': case_id})['task_id']


def plans(client, sid):
    return client.call('plan_candidates', {'task_id': sid})['candidates']


def choose(items):
    found = next((p for p in items if p['robust']['feasible']), None)
    require(found is not None, '没有找到通过验证的路线。')
    return found


def step(client, sid, route, pack):
    args = {'task_id': sid, 'route': route, 'pack': pack}
    result = client.call('simulate_plan', args)
    require(result['feasible'], 'simulate_plan 未通过约束验证。')
    result = client.call('execute_step', args)
    require(result['state']['node'] == route[1], '单段执行未到达预期的下一节点。')
    return result


def finish(client, sid, route, pack):
    remaining = list(route)
    while len(remaining) > 1:
        step(client, sid, remaining, pack)
        remaining = remaining[1:]


def verify(client, sid):
    return client.call('verify_delivery', {'task_id': sid})


def record_result(client, sid, expected, route=None, pack=None):
    actual = verify(client, sid)
    require(actual['status'] == expected, '预期 ' + expected + '，实际 ' + actual['status'])
    require(actual['measured_hardware'] is False, '仿真结果不应标记为硬件实测。')
    evidence = client.call('export_evidence', {'task_id': sid})
    path = Path(evidence['local_file'])
    require(path.is_file(), '证据文件未生成。')
    payload = json.loads(path.read_text(encoding='utf-8'))
    require(payload['task_id'] == sid and payload['sha256'] == evidence['sha256'], '证据文件与工具返回不一致。')
    require(payload['agh_session_verified'] is False, '本机检查不能证明 AGH 已执行。')
    client.saved_evidence.mkdir(parents=True, exist_ok=True)
    saved = client.saved_evidence / path.name
    saved.write_bytes(path.read_bytes())
    return {'task_id': sid, 'status': actual['status'], 'verification': actual,
            'route': route, 'pack': pack, 'evidence_file': str(saved.relative_to(ROOT)), 'sha256': evidence['sha256'], 'payload': payload}


def normal(client):
    sid = create(client, case_id='normal')
    selected = choose(plans(client, sid))
    finish(client, sid, selected['route'], selected['pack'])
    result = record_result(client, sid, 'DELIVERED', selected['route'], selected['pack'])
    v = result['verification']
    require(v['node'] == 'D' and v['sensor_ok'], '未到达 D 或传感器异常。')
    require(2 <= v['temperature_c'] <= 8 and v['time_min'] <= 25 and v['energy_wh'] <= 285, '默认交付约束未满足。')
    return result


def closure(client):
    sid = create(client, case_id='closure')
    initial = plans(client, sid)
    require(any(p['route'] == ['A', 'B', 'R', 'D'] and p['pack'] == 'enhanced' and p['robust']['feasible'] for p in initial), '封路测试初始方案不可行。')
    step(client, sid, ['A', 'B', 'R', 'D'], 'enhanced')
    step(client, sid, ['B', 'R', 'D'], 'enhanced')
    before = verify(client, sid)
    client.call('inject_event', {'task_id': sid, 'event_type': 'closure', 'value': 'R-D'})
    after = verify(client, sid)
    for key in ['node', 'time_min', 'energy_wh', 'temperature_c']:
        require(after[key] == before[key], '注入事件错误地重置或改写了 ' + key)
    selected = choose(plans(client, sid))
    require(selected['route'][0] == 'R' and selected['pack'] == 'enhanced', '重规划起点或包装不正确。')
    edges = list(zip(selected['route'], selected['route'][1:]))
    require(('R', 'D') not in edges and ('D', 'R') not in edges, '重规划仍经过已封闭航路。')
    finish(client, sid, selected['route'], selected['pack'])
    result = record_result(client, sid, 'DELIVERED', ['A', 'B', 'R'] + selected['route'][1:], 'enhanced')
    require(result['verification']['replans'] == 1, '封路事件未登记。')
    return result


def sensor_failure(client):
    sid = create(client, case_id='sensor_failure')
    selected = choose(plans(client, sid))
    moved = step(client, sid, selected['route'], selected['pack'])
    client.call('inject_event', {'task_id': sid, 'event_type': 'sensor_failure'})
    observed = verify(client, sid)
    require(observed['status'] == 'UNVERIFIED' and observed['sensor_ok'] is False, '传感器失效后仍可验证交付。')
    error = client.call('execute_step', {'task_id': sid, 'route': selected['route'][1:], 'pack': selected['pack']}, expect_error=True)
    client.call('abort_task', {'task_id': sid, 'reason': '温度传感器失效；停止仿真任务并转人工处理。'})
    result = record_result(client, sid, 'ABORTED', selected['route'][:2], selected['pack'])
    require(result['verification']['node'] == moved['state']['node'], '故障之后位置发生了变化。')
    result['execution_rejection'] = error
    return result


def wind(client):
    sid = create(client, case_id='wind')
    selected = choose(plans(client, sid))
    step(client, sid, selected['route'], selected['pack'])
    client.call('inject_event', {'task_id': sid, 'event_type': 'wind', 'value': 6})
    require(not any(p['robust']['feasible'] for p in plans(client, sid)), '逆风测试存在可行方案，需复核默认模型。')
    client.call('abort_task', {'task_id': sid, 'reason': '逆风增加后没有满足全部约束的剩余方案。'})
    return record_result(client, sid, 'ABORTED', selected['route'][:2], selected['pack'])


def heat(client):
    sid = create(client, {'ambient_c': 38}, 'heat')
    selected = choose(plans(client, sid))
    finish(client, sid, selected['route'], selected['pack'])
    return record_result(client, sid, 'DELIVERED', selected['route'], selected['pack'])


def blocked(client, config, reason):
    sid = create(client, config, 'boundary' if 'deadline_min' in config else 'low_battery')
    require(not any(p['robust']['feasible'] for p in plans(client, sid)), reason + '：仍发现可行方案。')
    client.call('abort_task', {'task_id': sid, 'reason': reason})
    result = record_result(client, sid, 'ABORTED')
    require(result['verification']['node'] == 'A' and result['verification']['energy_wh'] == 0, '拒绝起飞测试仍发生了执行。')
    return result


def persistence(client):
    sid = create(client)
    selected = choose(plans(client, sid))
    step(client, sid, selected['route'], selected['pack'])
    client.call('inject_event', {'task_id': sid, 'event_type': 'sensor_failure'})
    before = verify(client, sid)
    client.restart()
    after = verify(client, sid)
    require(before == after and after['sensor_ok'] is False, '服务重启后任务状态丢失。')
    client.call('abort_task', {'task_id': sid, 'reason': '重启持久化测试完成。'})
    return record_result(client, sid, 'ABORTED')


def isolation(client):
    first, second = create(client), create(client)
    client.call('inject_event', {'task_id': first, 'event_type': 'sensor_failure'})
    require(verify(client, first)['sensor_ok'] is False, '目标任务未生效。')
    require(verify(client, second)['sensor_ok'] is True, '错误地修改了另一个任务。')
    client.call('inject_event', {'task_id': 'aaaaaaaaaaaa', 'event_type': 'sensor_failure'}, expect_error=True)
    client.call('abort_task', {'task_id': first, 'reason': '任务隔离检查完成。'})
    return record_result(client, first, 'ABORTED')


def invalid_events(client):
    sid = create(client)
    before = verify(client, sid)
    for event_type, value in [('closure', 'A-X'), ('wind', 11), ('wind', True), ('wind', 'six')]:
        client.call('inject_event', {'task_id': sid, 'event_type': event_type, 'value': value}, expect_error=True)
        require(verify(client, sid) == before, '无效事件改变了任务状态。')
    client.call('not_a_tool', {}, expect_error=True)
    client.call('create_task', {'config': None}, expect_error=True)
    client.call('create_task', {'config': {}, 'case_id': 'invented'}, expect_error=True)
    client.call('execute_step', {'task_id': sid, 'route': [], 'pack': 'enhanced'}, expect_error=True)
    client.call('abort_task', {'task_id': sid, 'reason': '无效事件拒绝测试完成。'})
    return record_result(client, sid, 'ABORTED')


def main():
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    report = {'scope': 'local_stdio_simulation_only', 'utc': stamp,
              'runtime': {'python': sys.version, 'python_executable': sys.executable, 'platform': sys.platform},
              'agh_session_verified': False, 'model_calls_recorded_here': False,
              'measured_hardware': False, 'tool_trace': [], 'cases': [], 'overall_passed': False}
    client = None
    try:
        files = EVIDENCE_SOURCES
        report['source_sha256'] = {n: hashlib.sha256((ROOT / n).read_bytes()).hexdigest() for n in files}
        client = MCP(report['tool_trace'])
        report['servers'], report['catalogs'] = client.servers, client.catalogs
        print('PASS：单一服务发现全部 8 个工具，包含 inject_event。')
        tests = [('正常配送', normal), ('途中封路', closure), ('传感器故障', sensor_failure),
                 ('逆风增加', wind),
                 ('12 分钟时限', lambda c: blocked(c, {'deadline_min': 12}, '时限约束不满足。')),
                 ('55 Wh 电量不足', lambda c: blocked(c, {'battery_wh': 55}, '电量约束不满足。')),
                 ('服务重启后状态保留', persistence), ('不同任务相互隔离', isolation),
                 ('错误事件拒绝且状态不变', invalid_events), ('38 C 高温配送', heat)]
        for title, test in tests:
            try:
                result = test(client)
                report['cases'].append({'name': title, 'passed': True, **result})
                print('PASS：' + title + ' → ' + result['status'])
            except Exception as exc:
                report['cases'].append({'name': title, 'passed': False, 'error': str(exc)})
                raise
        report['overall_passed'] = True
        print('\n本地 stdio 检查通过；事件、执行和重规划使用同一持久化任务。')
    except Exception as exc:
        report['error'] = str(exc)
        print('FAIL：' + str(exc))
    finally:
        if client is not None:
            client.close()
        out = ROOT / 'evidence' / 'local_tests' / ('project_check_' + stamp + '.json')
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print('报告：' + str(out))
        print('以上是本地仿真测试；AGH 模型实际调用须另存“痕迹”。')
    return 0 if report['overall_passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())

