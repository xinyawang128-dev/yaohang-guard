"""Cross-platform entry point; Python 3.10+, standard library only."""
import argparse
import subprocess
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parent
COMMANDS={'check':'run_checks.py','serve':'server.py','register':'register_agh.py',
          'check-agh':'check_agh.py','prompts':'open_instructions.py',
          'export-session':'export_agh_session.py','collect':'collect_results.py','offline':'cli.py'}

if __name__=='__main__':
    parser=argparse.ArgumentParser(description='药航守护工程入口；check 不调用模型，register 连接已有 AGH。')
    parser.add_argument('command',choices=COMMANDS)
    args,rest=parser.parse_known_args()
    if sys.version_info<(3,10): parser.error('需要 Python 3.10+')
    raise SystemExit(subprocess.run([sys.executable,'-X','utf8',str(ROOT/COMMANDS[args.command]),*rest],cwd=ROOT).returncode)
