"""Frozen competition test fixtures, shared by prompts and collection checks."""
from engine import SCENARIOS, validate_config

REQUIRED = ['normal', 'closure', 'boundary', 'sensor_failure']
OPTIONAL = ['wind', 'low_battery', 'heat']
TITLES = {k: v['title'] for k, v in SCENARIOS.items()}


def expected_config(case_id):
    return validate_config(SCENARIOS[case_id]['config'])


def check_case(report):
    """Check conditions and behavior; a correct safe refusal also passes a test."""
    errors = []
    case = report.get('case_id')
    if case not in SCENARIOS:
        return ['缺少受支持的 case_id；请按测试指令重新创建任务。']
    if report.get('initial_config') != expected_config(case):
        errors.append('初始参数与固定用例不一致；不能通过放宽约束完成测试。')
    v, trace = report.get('verification', {}), report.get('tool_rpc_trace', [])
    tools = [r.get('tool') for r in trace]
    expected_final = expected_config(case)
    if case == 'closure':
        expected_final['closed_edges'] = ['R-D']
    if case == 'wind':
        expected_final['headwind_ms'] = 6
    if report.get('config') != expected_final:
        errors.append('最终条件与指定事件不一致。')
    events = [r for r in trace if r.get('tool') == 'inject_event']
    if len(events) != (1 if case in ['closure', 'sensor_failure', 'wind'] else 0):
        errors.append('故障事件数量与用例不一致。')
    for name in ['create_task', 'plan_candidates', 'verify_delivery']:
        if name not in tools:
            errors.append('缺少工具调用：' + name)
    initial = report.get('initial_candidates', [])
    feasible = [p for p in initial if p.get('robust', {}).get('feasible')]
    if case in ['normal', 'closure', 'heat']:
        if v.get('status') != 'DELIVERED' or v.get('node') != 'D' or v.get('sensor_ok') is not True:
            errors.append('未完成可验证配送。')
        c = expected_config(case)
        if not (c['lower_c'] <= v.get('temperature_c', -999) <= c['upper_c'] and
                v.get('time_min', 999) <= c['deadline_min'] and v.get('energy_wh', 9999) <= c['battery_wh']-c['reserve_wh']):
            errors.append('温度、时限或电量约束未满足。')
        if not feasible or not all(t in tools for t in ['simulate_plan', 'execute_step']):
            errors.append('缺少可行初始方案或仿真／执行过程。')
    if case in ['boundary', 'low_battery']:
        if feasible or v.get('status') != 'ABORTED' or v.get('node') != 'A' or v.get('energy_wh') != 0 or 'execute_step' in tools:
            errors.append('无解用例应在 A 拒绝起飞并中止，不能发生执行。')
    if case in ['closure', 'sensor_failure', 'wind']:
        wanted = 'closure' if case == 'closure' else case
        event = next((r for r in events if r.get('arguments', {}).get('event_type') == wanted), None)
        if event is None:
            errors.append('缺少指定故障注入。')
        else:
            pos = trace.index(event)
            before = [r for r in trace[:pos] if r.get('tool') == 'execute_step']
            if case == 'closure':
                state = event.get('result', {}).get('state', {})
                if event['arguments'].get('value') != 'R-D' or state.get('node') != 'R' or len(before) != 2:
                    errors.append('必须在 A→B→R 后注入 R-D 封路。')
                after_plans = [r for r in trace[pos+1:] if r.get('tool') == 'plan_candidates']
                if not after_plans or not all(p.get('route', [None])[0] == 'R' and p.get('pack') == 'enhanced' for p in after_plans[0].get('result', {}).get('candidates', [])):
                    errors.append('缺少从 R 开始、保留原包装的重新规划。')
                for r in trace[pos+1:]:
                    if r.get('tool') == 'execute_step':
                        route = r['arguments']['route']
                        if any({a,b} == {'R','D'} for a,b in zip(route,route[1:])):
                            errors.append('封路后仍执行 R-D。')
            elif case == 'sensor_failure':
                if len(before) != 1 or v.get('status') != 'ABORTED' or v.get('sensor_ok') is not False:
                    errors.append('传感器故障应在第一段后触发并中止。')
                if any(r.get('tool') == 'execute_step' for r in trace[pos+1:]):
                    errors.append('传感器故障后仍成功推进状态。')
            else:
                if event['arguments'].get('value') != 6 or len(before) != 1 or v.get('status') != 'ABORTED':
                    errors.append('逆风 6 m/s 应在第一段后触发并停止仿真任务并转人工处理。')
    return errors
