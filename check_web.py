"""Loopback HTTP regressions, optionally with a real browser. No model calls."""
import argparse
import datetime
import json
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError
import server
from engine import verify_report
from agh_common import ROOT, save_json

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--browser',action='store_true');parser.add_argument('--node',default='node');parser.add_argument('--chrome');parser.add_argument('--qa-dir');args=parser.parse_args()
    checks=[]
    with tempfile.TemporaryDirectory(prefix='yaohang_http_') as directory:
        temporary=Path(directory);server.TASKS=temporary/'tasks';server.TASKS.mkdir()
        http=server.ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
        thread=threading.Thread(target=http.serve_forever,daemon=True);thread.start()
        url='http://127.0.0.1:'+str(http.server_port)
        def request(path,body=None,origin=None):
            headers={'Content-Type':'application/json'}
            if origin:headers['Origin']=origin
            req=Request(url+path,data=json.dumps(body).encode() if body is not None else None,headers=headers)
            try:
                with urlopen(req,timeout=10) as response:
                    raw=response.read();kind=response.headers.get('Content-Type','')
                    return response.status,json.loads(raw) if 'application/json' in kind else raw.decode()
            except HTTPError as error:return error.code,json.loads(error.read())
        try:
            status,html=request('/');assert status==200 and '/app.js' in html
            status,js=request('/app.js');assert status==200 and 'refreshSaved' in js
            checks.append('HTML 与独立 JavaScript 正常提供')
            status,meta=request('/api/meta');assert status==200 and len(meta['scenarios'])==7
            checks.append('元数据接口返回七个场景与当前版本')
            assert request('/api/agh-reports')==(200,[])
            checks.append('无任务时返回空列表')
            expected={'normal':'DELIVERED','closure':'DELIVERED','boundary':'ABORTED','sensor_failure':'ABORTED','wind':'ABORTED','low_battery':'ABORTED','heat':'DELIVERED'}
            for case,state in expected.items():
                status,report=request('/api/run',{'scenario':case})
                assert status==200 and report['verification']['status']==state and verify_report(report)
                assert report['origin']=='local_offline' and not report['model_calls_recorded_here']
            checks.append('七个离线 HTTP 场景结果和完整性正确且无模型声明')
            status,report=request('/api/run',{'scenario':'normal','overrides':{'headwind_ms':10}})
            assert status==200 and report['verification']['status']=='ABORTED'
            checks.append('极端逆风返回可解释中止而非服务器异常')
            assert request('/api/run',{'unexpected':True})[0]==400
            assert request('/api/run',{'scenario':'normal','overrides':{'battery_wh':1}})[0]==400
            assert request('/api/run',{'scenario':'normal'},'https://invalid.example')[0]==403
            checks.append('错误参数和跨来源请求被拒绝')
            assert request('/api/report?task_id=../../secret')[0]==400
            (server.TASKS/'mcp_corrupt.json').write_text('[]')
            assert request('/api/agh-reports')==(200,[])
            checks.append('无效任务 ID 与损坏的 JSON 不会使结果列表崩溃')
            reports={}
            for source in sorted((ROOT/'evidence'/'local_tests').rglob('mcp_*.json')):
                report=json.loads(source.read_text())
                if server.valid_task_report(report):reports[report['case_id']]=(source,report)
            assert all(case in reports for case in expected)
            for case,(source,report) in reports.items():shutil.copyfile(source,server.TASKS/source.name)
            status,listing=request('/api/agh-reports');assert status==200 and len(listing)==len(reports)
            task=reports['normal'][1]
            status,loaded=request('/api/report?task_id='+task['task_id']);assert status==200 and loaded==task
            checks.append('本机 MCP 导出可列出并按任务 ID 原样读取')
            if args.browser:
                qa=Path(args.qa_dir or ROOT/'evidence'/'local_tests'/'browser_qa');qa.mkdir(parents=True,exist_ok=True)
                command=[args.node,str(ROOT/'tests'/'browser_smoke.cjs'),url,str(qa)]
                if args.chrome:command.append(args.chrome)
                subprocess.run(command,cwd=ROOT,check=True,timeout=90)
            for case in checks:print('PASS：'+case)
            stamp=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
            save_json(ROOT/'evidence'/'local_tests'/('web_check_'+stamp+'.json'),{'scope':'loopback_http_local_validation','overall_passed':True,'count':len(checks),'cases':checks,'agh_session_verified':False,'fixtures':'local MCP exports copied into temporary directory; removed after check','browser_requested':args.browser})
        finally:http.shutdown();http.server_close();thread.join(timeout=3)
    return 0

if __name__=='__main__':raise SystemExit(main())
