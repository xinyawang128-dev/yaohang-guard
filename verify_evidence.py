import argparse
import json
from pathlib import Path
from engine import verify_report

if __name__=='__main__':
    parser=argparse.ArgumentParser(description='Verify evidence content integrity, not model identity')
    parser.add_argument('file');args=parser.parse_args()
    try:ok=verify_report(json.loads(Path(args.file).read_text(encoding='utf-8')))
    except (OSError,ValueError,TypeError):ok=False
    print('PASS: evidence content matches checksum' if ok else 'FAIL: evidence missing or changed')
    raise SystemExit(0 if ok else 1)
