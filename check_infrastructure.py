"""Negative checks. Synthetic ledger fixtures exist only in tempdirs."""
import copy
import datetime
import json
import tempfile
from pathlib import Path
from agh_common import ROOT, SERVER_ID, AGHError, save_json
from register_agh import register
from check_agh import inspect
from collect_results import collect, inspect_reports, evidence_ready, missing_materials, url_ok, build_zip
from engine import seal_report
from mcp_runtime import TOOLS
from agh_evidence import read_ledger, match_task


def need(condition, message):
    if not condition:
        raise AssertionError(message)


def main():
    cases = []
    rev = 'a'*64
    descriptor = SERVER_ID+' revision='+rev+' trust=trusted desired=enabled actual=enabled transport=stdio'
    def reads(args):
        if args == ['mcp','list']: return 'No MCP servers found.'
        if args == ['mcp','get',SERVER_ID]: return descriptor
        if args == ['mcp','status',SERVER_ID]: return SERVER_ID+' connection=ready revision='+rev+' catalog='+rev+' tools=8'
        if args == ['mcp','tools',SERVER_ID]: return '\n'.join(t['name']+' — fixture description' for t in TOOLS)
        raise AssertionError('unexpected command '+str(args))
    commands = []
    register({}, [], read=reads, mutate=commands.append)
    command = commands[0]
    need(command[:3] == ['mcp','add',SERVER_ID], 'registration must add the one final ID')
    allow = [command[i+1] for i,v in enumerate(command) if v=='--allow-tool']
    need(allow == [t['name'] for t in TOOLS], 'all eight tools must be allowlisted')
    need('--arg=-u' not in command and '--arg' in command and '-u' in command, 'repeat official --arg grammar')
    cases.append('官方 CLI 新增命令、8 工具白名单和 stdio 参数')
    def existing(args): return descriptor if args==['mcp','list'] else reads(args)
    commands=[]; register({}, [], read=existing, mutate=commands.append)
    need(commands[0][:5]==['mcp','update',SERVER_ID,'--expected-revision',rev], 'latest revision required on update')
    cases.append('更新时读取并携带最新 revision')
    commands=[]
    try:
        register({}, [], read=lambda _: 'unknown old CLI format', mutate=commands.append)
        raise AssertionError('unrecognized listing accepted')
    except AGHError:
        need(not commands, 'must not mutate on an unrecognized listing')
    cases.append('无法识别 CLI 列表时停止修改')
    need(inspect({}, [], read=reads)['catalog_ready'], '8 tool catalog should be ready')
    def missing(args):
        if args==['mcp','tools',SERVER_ID]: return '\n'.join(t['name'] for t in TOOLS if t['name']!='inject_event')
        return reads(args)
    need(inspect({}, [], read=missing)['missing']==['inject_event'] and not inspect({}, [], read=missing)['catalog_ready'], '7 tool catalog must fail')
    cases.append('AGH 目录缺少 inject_event 时不判定就绪')
    def stale(args):
        result=reads(args)
        return result.replace('catalog='+rev,'catalog='+'b'*64) if args==['mcp','status',SERVER_ID] else result
    need(not inspect({},[],read=stale)['catalog_ready'],'stale catalog revision must not count as ready')
    cases.append('工具齐全但目录 revision 过期时不判定就绪')
    reports={}
    for path in sorted((ROOT/'evidence'/'local_tests').rglob('mcp_*.json')):
        r=json.loads(path.read_text(encoding='utf-8')); reports[r['case_id']]=r
    need(all(c in reports for c in ['normal','closure','boundary','sensor_failure']), 'run check_project.py first')
    with tempfile.TemporaryDirectory(prefix='yaohang_negative_checks_') as directory:
        temp=Path(directory); tasks=temp/'tasks'; sessions=temp/'sessions'; tasks.mkdir(); sessions.mkdir()
        for case in ['normal','closure','boundary','sensor_failure']:
            r=reports[case]; save_json(tasks/('mcp_'+r['task_id']+'.json'),r)
        result=collect(ROOT,tasks,sessions)
        need(result['engineering_cases_complete'] and not result['native_agh_evidence_observed'] and len(result['pending_agh_cases'])==4, 'local data must not count as AGH proof')
        cases.append('4 个真实本机用例齐全仍不能冒充 AGH 会话')
        normal=copy.deepcopy(reports['normal']); normal['verification']['time_min']=0
        path=tasks/('mcp_'+normal['task_id']+'.json'); save_json(path,normal)
        need(not next(i for i in inspect_reports(tasks) if i['task_id']==normal['task_id'])['valid'], 'tampered hash must fail')
        cases.append('篡改数值后 SHA256 校验拒绝')
        normal=copy.deepcopy(reports['normal']); normal['initial_config']['deadline_min']=999; seal_report(normal); save_json(path,normal)
        need(not next(i for i in inspect_reports(tasks) if i['task_id']==normal['task_id'])['valid'], 'relaxed conditions must fail even with valid hash')
        cases.append('重算哈希也不能通过放宽比赛用例参数')
        save_json(sessions/'not_a_ledger.jsonl', {'task_id': reports['normal']['task_id'], 'model':'agnes-3.0-flash', 'success':True})
        need(not read_ledger(sessions/'not_a_ledger.jsonl')['recognized_native_structure'], 'plain claimed success must fail')
        cases.append('写明 Agnes 和 success 的普通 JSON 不充当会话')
        # This is a parser unit fixture, never an actual AGH session.
        r=reports['normal']; events=[]
        actor={'id':'unit-test','org':'','role':'','deptPath':[],'attrs':{}}
        def emit(typ,data,origin='system'):
            seq=len(events)+1
            events.append({'seq':seq,'ts':'2026-10-11T00:00:00Z','id':str(seq).zfill(26),'type':typ,'data':data,'actor':actor,'origin':origin,'trust':'trusted'})
        emit('session/start', {'key':'UNIT_TEST_NOT_A_REAL_SESSION','agnesVersion':'unit-test'})
        emit('step/start',{'turn':1,'step':1})
        emit('request/sent',{'model':{'route':'unit-test','id':'agnes-3.0-flash'}})
        expected=[(x['tool'],x['arguments'],x['result']) for x in r['tool_rpc_trace']]
        expected.append(('export_evidence',{'task_id':r['task_id']},{'sha256':r['sha256']}))
        for i,(name,args,value) in enumerate(expected):
            emit('tool/call',{'toolUseId':str(i),'name':'mcp__yaohang_guard_final__'+name,'args':args,'ordinal':i},'model')
            emit('tool/result',{'toolUseId':str(i),'content':[{'type':'text','text':json.dumps(value)}],'isError':False},'tool:unit-test')
        fixture=sessions/'unit_fixture.jsonl'
        fixture.write_text('\n'.join(json.dumps(e) for e in events)+'\n',encoding='utf-8')
        matched=match_task(r,[read_ledger(fixture)])
        need(matched['native_tool_chain_matched'] and matched['agnes_core_calls_observed'] and matched['authenticity_verified'] is False,'match structure without claiming authenticity')
        cases.append('原生格式调用链按参数／结果匹配，真实性仍需人工核查')
        events[2]['data']['model']['id']='other-model'
        fixture.write_text('\n'.join(json.dumps(e) for e in events)+'\n',encoding='utf-8')
        matched=match_task(r,[read_ledger(fixture)])
        need(matched['native_tool_chain_matched'] and not matched['agnes_core_calls_observed'],'another model cannot be labeled Agnes')
        cases.append('其他模型元数据不会被标成 Agnes')
        events[2]['data']['model']['id']='agnes-3.0-flash'
        emit('step/start',{'turn':2,'step':1})
        emit('request/sent',{'model':{'id':'other-model'}})
        fixture.write_text('\n'.join(json.dumps(e) for e in events)+'\n',encoding='utf-8')
        matched=match_task(r,[read_ledger(fixture)])
        need(matched['agnes_core_calls_observed'] and not matched['all_session_models_agnes'] and not evidence_ready({'agh':matched}),'mixed session must not pass whole-session model rule')
        cases.append('核心调用是 Agnes 但会话混用其他模型时不通过预检查')
        events.pop();emit('request/sent',{'model':{}})
        fixture.write_text('\n'.join(json.dumps(e) for e in events)+'\n',encoding='utf-8')
        ledger=read_ledger(fixture)
        need(ledger['unknown_model_requests']==1 and not ledger['all_session_models_agnes'],'unknown model request must remain pending')
        cases.append('存在无法识别模型的请求时保持待核查状态')
        need(not url_ok('https://[invalid'),'malformed URL must be rejected without raising')
        info={'members':[{'name':'x','role':'y','signed_statement_file':'missing.pdf'}]*4,'models_used':[{'name':'Agnes','version':123}]}
        need(missing_materials(info,ROOT),'invalid member count and typed fields must be reported')
        cases.append('畸形链接、四人成员及错误字段类型被列为缺项')
        code=temp/'code';out=code/'submission';out.mkdir(parents=True)
        (code/'.env').write_text('unit fixture, not a secret')
        (code/'README.md').write_text('fixture')
        (code/'evidence'/'local_tests').mkdir(parents=True)
        (code/'evidence'/'local_tests'/'local.json').write_text('{}')
        archive=build_zip(code,out,'fixture.zip')
        import zipfile
        with zipfile.ZipFile(archive) as z:
            need(z.namelist()==['yaohang_guard_agh_final/README.md'],'local checks and .env must be excluded from contest ZIP')
        cases.append('比赛整理包排除环境文件与本机仿真检查证据')
    for case in cases: print('PASS：'+case)
    stamp=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    save_json(ROOT/'evidence'/'local_tests'/('infrastructure_check_'+stamp+'.json'), {
        'scope':'local_unit_and_negative_checks_only','overall_passed':True,'count':len(cases),'cases':cases,
        'agh_session_verified':False,'ledger_fixtures':'synthetic; temporary files removed; never submission evidence'})
    return 0


if __name__=='__main__':
    raise SystemExit(main())
