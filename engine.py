"""药航守护: deterministic engineering tools, Python 3.10+, no model calls."""
import copy
import datetime
import hashlib
import itertools
import json
import math
import random
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent

def canonical_json(value):
    """Stable across JSON clients that stringify 5.0 as 5 (e.g. browsers)."""
    def normalize(v):
        if isinstance(v,float) and v.is_integer(): return int(v)
        if isinstance(v,list): return [normalize(x) for x in v]
        if isinstance(v,dict): return {k:normalize(x) for k,x in v.items()}
        return v
    return json.dumps(normalize(value),ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)

def seal_report(payload):
    payload.pop('sha256',None)
    payload['sha256_scheme']='normalized-json-v1'
    payload['sha256']=hashlib.sha256(canonical_json(payload).encode()).hexdigest()
    return payload

def verify_report(payload):
    obj=copy.deepcopy(payload); digest=obj.pop('sha256',None)
    return digest==hashlib.sha256(canonical_json(obj).encode()).hexdigest()

NODES = {'A': [0, 0], 'B': [3, 0], 'C': [2, 3], 'E': [6, 3], 'D': [8, 0], 'R': [4, 1]}
# solar is a synthetic effective ambient temperature increment, not a radiation model.
EDGES = [('A','B',8), ('B','D',32), ('A','C',0), ('C','E',0), ('E','D',0), ('B','R',0), ('R','E',0), ('R','D',0)]
PACKS = {'standard': {'tau_min': 110, 'mass_kg': .5}, 'enhanced': {'tau_min': 280, 'mass_kg': 1.0}}
DEFAULT = {'ambient_c': 32, 'headwind_ms': 1, 'battery_wh': 320, 'reserve_wh': 35,
           'deadline_min': 25, 'initial_c': 5, 'lower_c': 2, 'upper_c': 8,
           'payload_kg': .5, 'ambient_uncertainty_c': 2, 'wind_uncertainty_ms': 2,
           'tau_uncertainty_fraction': .15, 'closed_edges': []}
SCENARIOS = {
    'normal': {'title':'常规配送', 'config': {}},
    'heat': {'title':'高温配送', 'config': {'ambient_c':38}},
    'closure': {'title':'途中航路封闭', 'config': {}, 'event': {'type':'closure'}},
    'wind': {'title':'途中逆风增加', 'config': {}, 'event': {'type':'wind', 'value':6}},
    'low_battery': {'title':'电量不足拒绝起飞', 'config': {'battery_wh':55}},
    'sensor_failure': {'title':'温度传感器失效', 'config': {}, 'event': {'type':'sensor_failure'}},
    'boundary': {'title':'交付时间边界', 'config': {'deadline_min':12}},
}

def number(value, name, low, high):
    if isinstance(value, bool) or not isinstance(value, (int,float)) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f'{name} must be finite in [{low}, {high}]')
    return float(value)

def validate_config(config):
    if not isinstance(config,dict) or set(config)-set(DEFAULT):
        raise ValueError('unknown configuration field')
    c = dict(DEFAULT, **config)
    bounds = {'ambient_c':(-20,60), 'headwind_ms':(0,10), 'battery_wh':(1,1000),
              'reserve_wh':(0,500), 'deadline_min':(.1,120), 'initial_c':(-20,40),
              'lower_c':(-20,30), 'upper_c':(-10,40), 'payload_kg':(0,2),
              'ambient_uncertainty_c':(0,5), 'wind_uncertainty_ms':(0,3),
              'tau_uncertainty_fraction':(0,.4)}
    for k,(lo,hi) in bounds.items(): c[k]=number(c[k],k,lo,hi)
    if c['lower_c']>=c['upper_c']: raise ValueError('lower_c must be below upper_c')
    if c['reserve_wh']>=c['battery_wh']: raise ValueError('reserve_wh must be below battery_wh')
    if not isinstance(c['closed_edges'],list): raise ValueError('closed_edges must be a list')
    valid={a+'-'+b for a,b,_ in EDGES}|{b+'-'+a for a,b,_ in EDGES}
    if any(e not in valid for e in c['closed_edges']): raise ValueError('unknown closed edge')
    return c

def edge(a,b):
    for x,y,s in EDGES:
        if {a,b}=={x,y}: return math.dist(NODES[a],NODES[b]),s
    raise ValueError('route contains a nonexistent edge')

def paths(start, closed):
    out=[]
    def walk(path):
        if path[-1]=='D': out.append(path); return
        for a,b,_ in EDGES:
            nxt=b if a==path[-1] else a if b==path[-1] else None
            if nxt and nxt not in path and a+'-'+b not in closed and b+'-'+a not in closed:
                walk(path+[nxt])
    walk([start]); return out

def thermal_step(t, ambient, dt, tau):
    return ambient+(t-ambient)*math.exp(-dt/tau)

def simulate(config, route, pack, state=None, perturb=(0,0,1)):
    c=validate_config(config)
    if pack not in PACKS: raise ValueError('unknown pack')
    if not isinstance(route,list) or not route or any(n not in NODES for n in route): raise ValueError('unknown route node')
    s=copy.deepcopy(state or {'node':'A','time_min':0.,'energy_wh':0.,'temperature_c':c['initial_c'], 'history':[]})
    if route[0]!=s['node']: raise ValueError('route must begin at current node')
    if not s['history']: s['history']=[{'node':s['node'],'time_min':s['time_min'],'energy_wh':s['energy_wh'],'temperature_c':s['temperature_c']}]
    ambient=c['ambient_c']+perturb[0]
    wind=c['headwind_ms']+perturb[1]
    speed=12-wind
    if speed<=1: raise ValueError('headwind leaves insufficient ground speed')
    tau=PACKS[pack]['tau_min']*perturb[2]
    total_mass=c['payload_kg']+PACKS[pack]['mass_kg']
    # Simplified constant cruise power, not manufacturer-calibrated performance.
    power=430+90*total_mass+12*wind*wind
    for a,b in zip(route,route[1:]):
        if a+'-'+b in c['closed_edges'] or b+'-'+a in c['closed_edges']: raise ValueError('route is closed')
        distance,solar=edge(a,b)
        dt=distance*1000/speed/60
        steps=max(1,math.ceil(dt/.25))
        for i in range(steps):
            s['time_min']+=dt/steps
            s['energy_wh']+=power*dt/steps/60
            s['temperature_c']=thermal_step(s['temperature_c'],ambient+solar,dt/steps,tau)
            s['history'].append({'node': b if i==steps-1 else a+'-'+b,
                                'time_min':s['time_min'], 'energy_wh':s['energy_wh'], 'temperature_c':s['temperature_c']})
        s['node']=b
    temps=[p['temperature_c'] for p in s['history']]
    # Integrated degree-minutes outside the selected window using trapezoids.
    exposure=0.
    for p,q in zip(s['history'],s['history'][1:]):
        f=lambda t:max(0,t-c['upper_c'])+max(0,c['lower_c']-t)
        exposure+=(f(p['temperature_c'])+f(q['temperature_c']))/2*(q['time_min']-p['time_min'])
    failures=[]
    if min(temps)<c['lower_c']-1e-9 or max(temps)>c['upper_c']+1e-9: failures.append('temperature')
    if s['time_min']>c['deadline_min']+1e-9: failures.append('deadline')
    if s['energy_wh']>c['battery_wh']-c['reserve_wh']+1e-9: failures.append('battery')
    return {'route':route,'pack':pack,'time_min':s['time_min'],'energy_wh':s['energy_wh'],
            'remaining_wh':c['battery_wh']-s['energy_wh'], 'peak_c':max(temps),'min_c':min(temps),
            'excursion_degree_min':exposure,'feasible':not failures,'failures':failures,'state':s}

def envelope(c, route, pack, state=None):
    # All 8 corners of the declared ambient/wind/tau uncertainty box.
    results=[]; unavailable=0
    for da,dw,f in itertools.product([-c['ambient_uncertainty_c'],c['ambient_uncertainty_c']],
                                     [0,c['wind_uncertainty_ms']],
                                     [1-c['tau_uncertainty_fraction'],1+c['tau_uncertainty_fraction']]):
        if 12-(c['headwind_ms']+dw)<=1:
            unavailable+=1
        else:
            results.append(simulate(c,route,pack,state,(da,dw,f)))
    failures=set(x for r in results for x in r['failures'])
    if unavailable: failures.add('ground_speed')
    return {'feasible':not unavailable and all(r['feasible'] for r in results),
            'time_max_min':None if unavailable else max(r['time_min'] for r in results),
            'energy_max_wh':None if unavailable else max(r['energy_wh'] for r in results),
            'peak_max_c':None if unavailable else max(r['peak_c'] for r in results),
            'min_min_c':None if unavailable else min(r['min_c'] for r in results),
            'failures':sorted(failures),'corners':8,'unflyable_corners':unavailable}

def candidates(config,state=None,fixed_pack=None):
    c=validate_config(config); out=[]
    for route in paths(state['node'] if state else 'A',c['closed_edges']):
        for pack in ([fixed_pack] if fixed_pack else PACKS):
            nominal=simulate(c,route,pack,state); nominal.pop('state')
            robust=envelope(c,route,pack,state)
            score=(robust['time_max_min']+.025*robust['energy_max_wh']+.7*PACKS[pack]['mass_kg']) if not robust['unflyable_corners'] else None
            out.append({'id':pack+':'+'-'.join(route),'route':route,'pack':pack,'nominal':nominal,'robust':robust,'score':score})
    return sorted(out,key=lambda x:(not x['robust']['feasible'],x['score'] if x['score'] is not None else math.inf))

class Session:
    """A tool session preserves physical state; model output cannot rewrite evidence."""
    def __init__(self,config=None,origin='local_offline'):
        self.config=validate_config(config or {})
        self.origin=origin
        self.id=uuid.uuid4().hex[:12]
        self.state={'node':'A','time_min':0.,'energy_wh':0.,'temperature_c':self.config['initial_c'],'history':[]}
        self.pack=None; self.aborted=False; self.reason=None; self.sensor_ok=True; self.log=[]; self.replans=0
        self.record('create_task',{'config':self.config})
    def record(self,tool,data):
        self.log.append({'sequence':len(self.log)+1,'utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'tool':tool,'data':copy.deepcopy(data)})
    def plan(self):
        if self.aborted: raise ValueError('task already aborted')
        out=candidates(self.config,self.state,self.pack)
        self.record('plan_candidates',{'current_node':self.state['node'],'candidates':out})
        return out
    def inspect(self,route,pack):
        if self.pack and pack!=self.pack: raise ValueError('pack cannot change after departure')
        result=envelope(self.config,route,pack,self.state)
        self.record('simulate_plan',{'route':route,'pack':pack,'envelope':result}); return result
    def step(self,route,pack):
        if self.aborted or not self.sensor_ok: raise ValueError('execution prohibited')
        if self.state['node']=='D': raise ValueError('task already delivered')
        if len(route)<2 or route[-1]!='D': raise ValueError('provide a complete route to D')
        if self.pack and pack!=self.pack: raise ValueError('pack cannot change after departure')
        check=self.inspect(route,pack)
        if not check['feasible']: raise ValueError('robust validation failed; replan or abort')
        self.pack=pack
        result=simulate(self.config,route[:2],pack,self.state)
        self.state=result['state']
        self.record('execute_step',{'route':route[:2],'pack':pack,'observation':{k:v for k,v in result.items() if k!='state'}})
        return {'state':self.state,'delivery_reached':self.state['node']=='D'}
    def event(self,event_type,value=None):
        if self.aborted or self.state['node']=='D': raise ValueError('cannot inject event into a finished task')
        if event_type=='closure':
            if not isinstance(value,str): raise ValueError('closure requires edge string')
            c=dict(self.config,closed_edges=self.config['closed_edges']+[value]); self.config=validate_config(c)
        elif event_type=='wind':
            self.config=validate_config(dict(self.config,headwind_ms=value))
        elif event_type=='sensor_failure': self.sensor_ok=False
        else: raise ValueError('unknown event')
        self.replans+=1; self.record('inject_event',{'type':event_type,'value':value,'state':self.state})
        return {'replan_required':True,'sensor_ok':self.sensor_ok}
    def abort(self,reason):
        if not isinstance(reason,str) or not reason.strip(): raise ValueError('abort requires reason')
        if self.state['node']=='D': raise ValueError('cannot abort a delivered task')
        if self.aborted: return {'status':'ABORTED','reason':self.reason,'node':self.state['node']}
        self.aborted=True; self.reason=reason; self.record('abort_task',{'reason':reason})
        return {'status':'ABORTED','reason':reason,'node':self.state['node']}
    def verify(self):
        if not self.sensor_ok: status='ABORTED' if self.aborted else 'UNVERIFIED'
        elif self.aborted: status='ABORTED'
        elif self.state['node']!='D': status='INCOMPLETE'
        else:
            check=simulate(self.config,['D'],self.pack,self.state)
            status='DELIVERED' if check['feasible'] else 'FAILED'
        result={'status':status,'node':self.state['node'],'sensor_ok':self.sensor_ok,'reason':self.reason,
                'time_min':self.state['time_min'],'energy_wh':self.state['energy_wh'], 'temperature_c':self.state['temperature_c'],
                'replans':self.replans,'measured_hardware':False}
        self.record('verify_delivery',result); return result
    def report(self):
        verification=self.verify()
        payload={'schema_version':1,'task_id':self.id,'origin':self.origin,'agh_session_verified':False,
                 'model_calls_recorded_here':False,'config':self.config,'pack':self.pack,'verification':verification,
                 'history':self.state['history'],'tool_trace':self.log,
                 'limitations':['synthetic map and parameters','no real drug stability or flight certification','external AGH transcript required']}
        return seal_report(payload)

def monte_carlo(config,plan,n=100,seed=2026):
    rng=random.Random(seed); c=validate_config(config); failures=0; peaks=[]
    for _ in range(n):
        perturb=(rng.uniform(-c['ambient_uncertainty_c'],c['ambient_uncertainty_c']),
                 rng.uniform(0,c['wind_uncertainty_ms']),
                 rng.uniform(1-c['tau_uncertainty_fraction'],1+c['tau_uncertainty_fraction']))
        r=simulate(c,plan['route'],plan['pack'],perturb=perturb)
        failures+=not r['feasible']; peaks.append(r['peak_c'])
    return {'samples':n,'seed':seed,'failures':failures,'simulated_pass_fraction':(n-failures)/n,
            'peak_c_max':max(peaks),'interpretation':'synthetic robustness check, not an empirical reliability estimate'}

def run_demo(scenario='normal',overrides=None):
    if scenario not in SCENARIOS: raise ValueError('unknown scenario')
    spec=SCENARIOS[scenario]; config=dict(spec['config'],**(overrides or {}))
    s=Session(config); initial=s.plan(); chosen=next((p for p in initial if p['robust']['feasible']),None)
    event=spec.get('event'); injected=False
    if not chosen: s.abort('在约束和不确定性范围内无可行计划，停止起飞')
    else:
        route=chosen['route']; pack=chosen['pack']
        while s.state['node']!='D' and not s.aborted:
            s.step(route,pack); route=route[1:]
            event_ready=event and (event['type']!='closure' or sum(t['tool']=='execute_step' for t in s.log)>=2)
            if event_ready and not injected and s.state['node']!='D':
                value=('-'.join(route[:2]) if event['type']=='closure' else event.get('value'))
                s.event(event['type'],value); injected=True
                if not s.sensor_ok: s.abort('温度观测缺失，无法验证冷链，要求人工接管当前节点'); break
                alternatives=s.plan(); new=next((p for p in alternatives if p['robust']['feasible']),None)
                if not new: s.abort('突发事件后无可行剩余航程，要求人工接管当前节点'); break
                route=new['route']
    report=s.report(); report['scenario']=scenario; report['title']=spec['title']; report['initial_candidates']=initial
    report['initial_config']=validate_config(config)
    baseline=sorted(initial,key=lambda p:(sum(edge(a,b)[0] for a,b in zip(p['route'],p['route'][1:])),p['pack']!='standard'))[0] if initial else None
    report['baseline_shortest_standard']=next((p for p in initial if baseline and p['route']==baseline['route'] and p['pack']=='standard'),baseline)
    report['same_pack_shortest']=next((p for p in initial if baseline and chosen and p['route']==baseline['route'] and p['pack']==chosen['pack']),None)
    report['initial_selected']=chosen
    report['monte_carlo_initial']=monte_carlo(s.config if not event else validate_config(config),chosen) if chosen else None
    # Seal the entire final exported object, including baseline comparisons.
    return seal_report(report)
