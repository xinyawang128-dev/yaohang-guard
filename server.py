"""Loopback demo and viewer for saved MCP task exports; no model invocation."""
import argparse
import json
import re
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from engine import DEFAULT, NODES, EDGES, SCENARIOS, PACKS, run_demo, verify_report
from project_info import VERSION

ROOT=Path(__file__).resolve().parent
TASKS=ROOT/'evidence'/'agh'/'tasks'

def valid_task_report(report):
    return (isinstance(report,dict) and report.get('origin')=='mcp_transport_unverified'
            and report.get('project_version')==VERSION and isinstance(report.get('tool_rpc_trace'),list)
            and isinstance(report.get('verification'),dict) and isinstance(report.get('initial_candidates'),list)
            and verify_report(report))


class Handler(BaseHTTPRequestHandler):
    def send(self,status,obj,mime='application/json; charset=utf-8'):
        data=json.dumps(obj,ensure_ascii=False,allow_nan=False).encode() if isinstance(obj,(dict,list)) else obj
        self.send_response(status); self.send_header('Content-Type',mime)
        self.send_header('Content-Length',str(len(data))); self.send_header('X-Content-Type-Options','nosniff')
        self.end_headers(); self.wfile.write(data)

    def do_GET(self):
        parsed=urlparse(self.path)
        if parsed.path=='/': self.send(200,(ROOT/'web/index.html').read_bytes(),'text/html; charset=utf-8')
        elif parsed.path=='/app.js': self.send(200,(ROOT/'web/app.js').read_bytes(),'text/javascript; charset=utf-8')
        elif parsed.path=='/api/meta': self.send(200,{'defaults':DEFAULT,'nodes':NODES,'edges':EDGES,'scenarios':SCENARIOS,'packs':PACKS,'version':VERSION})
        elif parsed.path=='/api/agh-reports':
            reports=[]
            for path in sorted(TASKS.glob('mcp_*.json')):
                try:
                    r=json.loads(path.read_text(encoding='utf-8'))
                    if valid_task_report(r): reports.append({'task_id':r['task_id'],'case_id':r.get('case_id','custom'),'title':r.get('title',r.get('case_id','自定义')),'status':r['verification']['status']})
                except (OSError, ValueError, KeyError, TypeError, AttributeError): pass
            self.send(200,reports)
        elif parsed.path=='/api/report':
            task_id=parse_qs(parsed.query).get('task_id',[''])[0]
            if not re.fullmatch('[a-f0-9]{12}',task_id): self.send(400,{'error':'任务 ID 无效'}); return
            try:
                r=json.loads((TASKS/('mcp_'+task_id+'.json')).read_text(encoding='utf-8'))
                if not valid_task_report(r): raise ValueError('证据结构或哈希不匹配')
                self.send(200,r)
            except (OSError,ValueError,TypeError,AttributeError,KeyError): self.send(404,{'error':'未找到完整有效的 MCP 导出；请先调用 export_evidence。'})
        else: self.send(404,{'error':'not found'})

    def do_POST(self):
        if self.path!='/api/run': self.send(404,{'error':'not found'}); return
        if self.headers.get('Origin') not in (None, f'http://127.0.0.1:{self.server.server_port}', f'http://localhost:{self.server.server_port}'):
            self.send(403,{'error':'origin denied'}); return
        try:
            size=int(self.headers.get('Content-Length',0))
            if not 0<size<=16384: raise ValueError('invalid request size')
            body=json.loads(self.rfile.read(size))
            if not isinstance(body,dict) or set(body)-{'scenario','overrides'}: raise ValueError('invalid body')
            self.send(200,run_demo(body.get('scenario','normal'),body.get('overrides')))
        except (ValueError,TypeError,KeyError) as e: self.send(400,{'error':str(e)})


if __name__=='__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('--port',type=int,default=8765); parser.add_argument('--open',action='store_true'); args=parser.parse_args()
    try:
        http=ThreadingHTTPServer(('127.0.0.1',args.port),Handler)
    except OSError as exc:
        print('端口已占用或无法启动：'+str(exc)+'\n可用 python server.py --port 8766 --open 换端口。'); raise SystemExit(1)
    url=f'http://127.0.0.1:{args.port}'
    print('药航守护 '+url+'；页面可查看 MCP 导出与离线演示。Ctrl+C 退出。',flush=True)
    if args.open: webbrowser.open(url)
    try: http.serve_forever()
    except KeyboardInterrupt: pass
    finally: http.server_close()
