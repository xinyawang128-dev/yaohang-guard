import argparse
import json
from pathlib import Path
from engine import SCENARIOS, run_demo

def main():
    p=argparse.ArgumentParser(description='药航守护 offline engineering demonstration; no model invocation')
    p.add_argument('--scenario',choices=SCENARIOS,default='normal')
    p.add_argument('--all',action='store_true')
    p.add_argument('--output',default=str(Path(__file__).resolve().parent/'evidence'/'offline'))
    a=p.parse_args(); out=Path(a.output); out.mkdir(parents=True,exist_ok=True)
    for name in (SCENARIOS if a.all else [a.scenario]):
        result=run_demo(name)
        (out/(name+'.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        print(name,json.dumps(result['verification'],ensure_ascii=False))

if __name__=='__main__': main()
