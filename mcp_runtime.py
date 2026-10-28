"""One AGH stdio catalog, eight tools, persistent simulation state."""
from project_info import VERSION, EVIDENCE_SOURCES
import argparse
import json
import re
import sqlite3
import sys

from task_store import TaskStore


def object_schema(properties, required):
    return {'type': 'object', 'properties': properties, 'required': required, 'additionalProperties': False}


SID = {'type': 'string', 'description': 'Actual task_id returned by this service create_task', 'pattern': '^[a-f0-9]{12}$'}
ROUTE = {'type': 'array', 'items': {'type': 'string', 'enum': ['A', 'B', 'C', 'D', 'E', 'R']}, 'minItems': 1, 'maxItems': 8}
PACK = {'type': 'string', 'enum': ['standard', 'enhanced']}
INJECT_TOOL = {
    'name': 'inject_event',
    'description': 'Inject a simulated fault into this task. closure: value="R-D"; wind: numeric value=6 m/s; sensor_failure: omit value. Returns physical state and changed event conditions. Retains the current position and resources.',
    'inputSchema': object_schema({
        'task_id': SID,
        'event_type': {'type': 'string', 'enum': ['closure', 'wind', 'sensor_failure']},
        'value': {'anyOf': [{'type': 'string'}, {'type': 'number'}, {'type': 'null'}]},
    }, ['task_id', 'event_type']),
}
MAIN_TOOLS = [
    {'name': 'create_task', 'description': 'Create a persistent synthetic delivery task. Supply case_id for competition test collection; returns actual task_id.',
     'inputSchema': object_schema({'case_id': {'type': 'string', 'enum': ['normal', 'closure', 'boundary', 'sensor_failure', 'wind', 'low_battery', 'heat', 'custom']}, 'config': {'type': 'object', 'description': 'Optional synthetic engine.DEFAULT settings'}}, [])},
    {'name': 'plan_candidates', 'description': 'Enumerate routes and packaging from the current shared task state; validate 8 uncertainty corners.',
     'inputSchema': object_schema({'task_id': SID}, ['task_id'])},
    {'name': 'simulate_plan', 'description': 'Validate the full remaining route before executing; packaging is fixed after departure.',
     'inputSchema': object_schema({'task_id': SID, 'route': ROUTE, 'pack': PACK}, ['task_id', 'route', 'pack'])},
    {'name': 'execute_step', 'description': 'Advance exactly one edge of the full remaining route to D; retain physical state in the shared store.',
     'inputSchema': object_schema({'task_id': SID, 'route': ROUTE, 'pack': PACK}, ['task_id', 'route', 'pack'])},
    {'name': 'abort_task', 'description': 'Stop the shared simulation task with an explicit reason.',
     'inputSchema': object_schema({'task_id': SID, 'reason': {'type': 'string', 'minLength': 1}}, ['task_id', 'reason'])},
    {'name': 'verify_delivery', 'description': 'Read current shared state; missing temperature sensor cannot validate delivery.',
     'inputSchema': object_schema({'task_id': SID}, ['task_id'])},
    {'name': 'export_evidence', 'description': 'Export actual simulation history and SHA256; attach an external AGH transcript to prove model execution.',
     'inputSchema': object_schema({'task_id': SID}, ['task_id'])},
]
TOOLS = MAIN_TOOLS[:4] + [INJECT_TOOL] + MAIN_TOOLS[4:]


def reject_constant(value):
    raise ValueError('non-finite JSON number: ' + value)


def validate_call(tools, name, args):
    spec = next((t for t in tools if t['name'] == name), None)
    if spec is None:
        raise ValueError('unknown tool in this service')
    schema = spec['inputSchema']
    if not isinstance(args, dict) or set(args) - set(schema['properties']):
        raise ValueError('unknown tool argument')
    if any(key not in args for key in schema['required']):
        raise ValueError('missing tool argument')
    if 'task_id' in args and (not isinstance(args['task_id'], str) or not re.fullmatch(r'[a-f0-9]{12}', args['task_id'])):
        raise ValueError('task_id must be the 12-character id returned by create_task')
    if 'config' in args and not isinstance(args['config'], dict):
        raise ValueError('config must be an object')
    if 'route' in args and (not isinstance(args['route'], list) or not 1 <= len(args['route']) <= 8 or any(n not in ['A', 'B', 'C', 'D', 'E', 'R'] for n in args['route'])):
        raise ValueError('invalid route')
    if 'pack' in args and args['pack'] not in ['standard', 'enhanced']:
        raise ValueError('unknown pack')
    if name == 'create_task' and args.get('case_id', 'custom') not in ['normal', 'closure', 'boundary', 'sensor_failure', 'wind', 'low_battery', 'heat', 'custom']:
        raise ValueError('unknown case_id')
    if name == 'inject_event':
        if args['event_type'] not in ['closure', 'wind', 'sensor_failure']:
            raise ValueError('unknown event_type')
        value = args.get('value')
        if value is not None and (isinstance(value, bool) or not isinstance(value, (str, int, float))):
            raise ValueError('value must be a string, number, or null')


def serve(role='full'):
    parser = argparse.ArgumentParser(description='Yaohang Guard final AGH MCP server')
    parser.add_argument('--database', help='Persistent SQLite task database')
    parser.add_argument('--evidence-dir', help='Simulation evidence directory')
    options = parser.parse_args()
    tools = TOOLS
    name = 'yaohang-guard-final'
    try:
        store = TaskStore(options.database, options.evidence_dir)
    except (OSError, sqlite3.Error) as exc:
        print('Cannot open task store: ' + str(exc), file=sys.stderr)
        return 1
    initialized = False
    for line in sys.stdin:
        ident = None
        try:
            request = json.loads(line, parse_constant=reject_constant)
            if not isinstance(request, dict) or request.get('jsonrpc') != '2.0':
                raise ValueError('JSON-RPC 2.0 object required')
            ident = request.get('id')
            method = request.get('method')
            if ident is None:
                continue
            params = request.get('params', {})
            if not isinstance(params, dict):
                raise ValueError('params must be an object')
            if method == 'initialize':
                initialized = True
                version = params.get('protocolVersion')
                result = {'protocolVersion': version if version in ['2024-11-05', '2025-03-26'] else '2025-03-26',
                          'capabilities': {'tools': {'listChanged': False}}, 'serverInfo': {'name': name, 'version': VERSION}}
            elif method == 'ping':
                result = {}
            elif not initialized:
                raise ValueError('initialize required')
            elif method == 'tools/list':
                result = {'tools': tools}
            elif method == 'tools/call':
                try:
                    tool_name, args = params.get('name'), params.get('arguments', {})
                    validate_call(tools, tool_name, args)
                    value = store.call(tool_name, args)
                    result = {'content': [{'type': 'text', 'text': json.dumps(value, ensure_ascii=False, allow_nan=False)}], 'isError': False}
                except (ValueError, KeyError, TypeError, OSError, sqlite3.Error) as exc:
                    result = {'content': [{'type': 'text', 'text': str(exc)}], 'isError': True}
            else:
                print(json.dumps({'jsonrpc': '2.0', 'id': ident, 'error': {'code': -32601, 'message': 'method not found'}}), flush=True)
                continue
            print(json.dumps({'jsonrpc': '2.0', 'id': ident, 'result': result}, ensure_ascii=False, allow_nan=False), flush=True)
        except (ValueError, KeyError, TypeError) as exc:
            print(json.dumps({'jsonrpc': '2.0', 'id': ident, 'error': {'code': -32602, 'message': str(exc)}}, ensure_ascii=False), flush=True)
    return 0
