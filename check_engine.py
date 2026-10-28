"""Analytical checks independent of the planner's own pass/fail flag."""
import copy
import datetime
import json
import math
from pathlib import Path
from engine import Session, simulate, candidates, DEFAULT, run_demo
from mcp_runtime import TOOLS
from agh_common import ROOT, save_json

def near(actual,expected):
    assert math.isclose(actual,expected,rel_tol=1e-10,abs_tol=1e-9),(actual,expected)

def main():
    tests=[]
    config=copy.deepcopy(DEFAULT)
    result=simulate(config,['A','B'],'enhanced')
    duration=3000/11/60
    energy=(430+90*1.5+12)*duration/60
    temperature=40+(5-40)*math.exp(-duration/280)
    near(result['time_min'],duration);near(result['energy_wh'],energy)
    tests.append('单段航时与恒定巡航功率独立手算一致')
    near(result['state']['temperature_c'],temperature)
    tests.append('分段积分温度与一阶换热闭式解一致')
    route=simulate(config,['A','C','E','D'],'enhanced')
    duration=(2*math.sqrt(13)+4)*1000/11/60
    near(route['state']['temperature_c'],32+(5-32)*math.exp(-duration/280))
    near(route['time_min'],duration)
    tests.append('多段无热暴露航路与总时长闭式解一致')
    heavier=simulate(dict(config,payload_kg=1),['A','B'],'enhanced')
    near(heavier['energy_wh']-result['energy_wh'],90*.5*result['time_min']/60)
    tests.append('载荷增量对能耗的影响与公式一致')
    nominal=dict(config,ambient_uncertainty_c=0,wind_uncertainty_ms=0,tau_uncertainty_fraction=0)
    route=simulate(nominal,['A','B','R','D'],'enhanced')
    limit=dict(nominal,battery_wh=route['energy_wh']+35)
    assert simulate(limit,['A','B','R','D'],'enhanced')['feasible']
    assert not simulate(dict(limit,battery_wh=limit['battery_wh']-.01),['A','B','R','D'],'enhanced')['feasible']
    tests.append('电量预留等号边界通过而少 0.01 Wh 被拒绝')
    assert not any(p['robust']['feasible'] for p in candidates(dict(config,initial_c=9)))
    tests.append('起始温度超限不会被终点温度掩盖')
    windy=candidates(dict(config,headwind_ms=10))
    assert windy and not any(p['robust']['feasible'] for p in windy)
    assert all('ground_speed' in p['robust']['failures'] and p['score'] is None for p in windy)
    json.dumps(windy,allow_nan=False)
    tests.append('极端逆风返回不可行角点且 JSON 不含 Infinity/NaN')
    demo=run_demo('normal',{'headwind_ms':10})
    assert demo['verification']['status']=='ABORTED' and demo['verification']['energy_wh']==0
    tests.append('极端逆风离线流程可解释地拒绝起飞')
    session=Session();plan=next(p for p in session.plan() if p['robust']['feasible']);remaining=plan['route'][:]
    while len(remaining)>1:
        session.step(remaining,plan['pack']);remaining=remaining[1:]
    snapshot=copy.deepcopy(session.__dict__)
    try: session.abort('不应覆盖已交付结果')
    except ValueError: pass
    else: raise AssertionError('delivered task accepted abort')
    assert snapshot==session.__dict__
    tests.append('完成配送后不能被中止调用覆盖结果')
    session=Session();session.abort('原始原因');session.abort('后续原因')
    assert session.reason=='原始原因' and len([t for t in session.log if t['tool']=='abort_task'])==1
    tests.append('重复中止保留原始原因且不重复修改状态')
    assert json.loads((ROOT/'mcp_tools.schema.json').read_text())==TOOLS
    tests.append('交付 Schema 文件与实际 MCP 工具目录一致')
    for name in tests:print('PASS：'+name)
    stamp=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    save_json(ROOT/'evidence'/'local_tests'/('engine_check_'+stamp+'.json'),{'scope':'independent_analytical_and_boundary_checks','overall_passed':True,'count':len(tests),'cases':tests,'agh_session_verified':False,'measured_hardware':False})
    return 0

if __name__=='__main__':raise SystemExit(main())
