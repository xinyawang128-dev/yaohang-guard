"""Persistent task state, successful RPC trace, and integrity-sealed exports."""
from project_info import VERSION, EVIDENCE_SOURCES
import copy
import datetime
import hashlib
import json
import re
import sqlite3
from contextlib import closing
from pathlib import Path

from engine import Session, seal_report, monte_carlo, edge, SCENARIOS
from inject_event import inject_event

ROOT = Path(__file__).resolve().parent


class TaskStore:
    def __init__(self, database=None, evidence_dir=None):
        self.database = Path(database or ROOT / 'data' / 'tasks.sqlite3').resolve()
        self.evidence_dir = Path(evidence_dir or ROOT / 'evidence' / 'agh' / 'tasks').resolve()
        self.database.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.database, timeout=15)) as db, db:
            db.execute('CREATE TABLE IF NOT EXISTS tasks (task_id TEXT PRIMARY KEY, snapshot TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS rpc_calls (seq INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT, tool TEXT, arguments TEXT, result TEXT, utc TEXT)')

    def call(self, name, args):
        with closing(sqlite3.connect(self.database, timeout=15)) as db, db:
            db.execute('BEGIN IMMEDIATE')
            if name == 'create_task':
                session = Session(args.get('config', {}), origin='mcp_transport_unverified')
                session.initial_config = copy.deepcopy(session.config)
                session.case_id = args.get('case_id', 'custom')
                result = {'task_id': session.id, 'config': session.config, 'agh_verified': False}
            else:
                task_id = args.get('task_id')
                if not isinstance(task_id, str) or not re.fullmatch(r'[a-f0-9]{12}', task_id):
                    raise ValueError('task_id must be the actual id returned by this project create_task')
                row = db.execute('SELECT snapshot FROM tasks WHERE task_id=?', (task_id,)).fetchone()
                if row is None:
                    raise ValueError('unknown task_id; use this service create_task first')
                session = Session.__new__(Session)
                session.__dict__.update(json.loads(row[0]))
                result = self._apply(session, name, args, db)
            snapshot = json.dumps(session.__dict__, ensure_ascii=False, allow_nan=False)
            db.execute('INSERT OR REPLACE INTO tasks(task_id,snapshot) VALUES(?,?)', (session.id, snapshot))
            db.execute('INSERT INTO rpc_calls(task_id,tool,arguments,result,utc) VALUES(?,?,?,?,?)',
                       (session.id, name, json.dumps(args, ensure_ascii=False, allow_nan=False),
                        json.dumps(result, ensure_ascii=False, allow_nan=False),
                        datetime.datetime.now(datetime.timezone.utc).isoformat()))
            return result

    def _apply(self, session, name, args, db):
        if name == 'plan_candidates':
            return {'candidates': session.plan()}
        if name == 'simulate_plan':
            return session.inspect(args['route'], args['pack'])
        if name == 'execute_step':
            return session.step(args['route'], args['pack'])
        if name == 'inject_event':
            return inject_event(session, args['event_type'], args.get('value'))
        if name == 'abort_task':
            return session.abort(args['reason'])
        if name == 'verify_delivery':
            return session.verify()
        if name == 'export_evidence':
            report = session.report()
            report['case_id'] = getattr(session, 'case_id', 'custom')
            report['scenario'] = report['case_id']
            report['title'] = SCENARIOS.get(report['case_id'], {}).get('title', '自定义任务')
            report['initial_config'] = getattr(session, 'initial_config', session.config)
            report['project_version'] = VERSION
            report['source_sha256'] = {n: hashlib.sha256((ROOT / n).read_bytes()).hexdigest()
                                       for n in EVIDENCE_SOURCES}
            rows = db.execute('SELECT seq,tool,arguments,result,utc FROM rpc_calls WHERE task_id=? ORDER BY seq', (session.id,)).fetchall()
            report['tool_rpc_trace'] = [{'sequence': r[0], 'tool': r[1], 'arguments': json.loads(r[2]),
                                         'result': json.loads(r[3]), 'utc': r[4]} for r in rows]
            initial = next((r['data']['candidates'] for r in session.log if r['tool'] == 'plan_candidates' and r['data']['current_node'] == 'A'), [])
            executed = next((r['arguments'] for r in report['tool_rpc_trace'] if r['tool'] == 'execute_step'), None)
            selected = next((p for p in initial if executed and p['route'] == executed['route'] and p['pack'] == executed['pack']), None)
            shortest = min(initial, key=lambda p: sum(edge(a, b)[0] for a, b in zip(p['route'], p['route'][1:])), default=None)
            same_pack = next((p for p in initial if selected and shortest and p['pack'] == selected['pack'] and p['route'] == shortest['route']), None)
            report.update(initial_candidates=initial, initial_selected=selected, same_pack_shortest=same_pack,
                          baseline_shortest_standard=next((p for p in initial if shortest and p['route'] == shortest['route'] and p['pack'] == 'standard'), None),
                          monte_carlo_initial=monte_carlo(report['initial_config'], selected) if selected else None)
            report = seal_report(report)
            self.evidence_dir.mkdir(parents=True, exist_ok=True)
            out = self.evidence_dir / ('mcp_' + session.id + '.json')
            temporary = out.with_suffix('.json.tmp')
            temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
            temporary.replace(out)
            return {'local_file': str(out), 'sha256': report['sha256'],
                    'verification': report['verification'], 'external_agh_transcript_required': True}
        raise ValueError('unknown tool')
