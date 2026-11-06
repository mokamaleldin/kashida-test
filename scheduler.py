"""Explicit bounded polling loop. Not started by GitHub or the dashboard."""
import argparse,fcntl,json,pathlib,subprocess,sys,time
ROOT=pathlib.Path(__file__).resolve().parent
p=argparse.ArgumentParser();p.add_argument('--cycles',type=int,default=1);p.add_argument('--send',action='store_true');a=p.parse_args()
if not 1<=a.cycles<=48:raise SystemExit('Choose 1..48 cycles. Default is one cycle only.')
s=json.loads((ROOT/'settings.json').read_text());minutes=int(s.get('interval_minutes',30))
if minutes<15:raise SystemExit('Minimum interval is 15 minutes')
(ROOT/'data').mkdir(exist_ok=True)
with (ROOT/'data/scheduler.lock').open('w') as lock:
 try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 except BlockingIOError:raise SystemExit('Another polling loop is active')
 for i in range(a.cycles):
  cmd=[sys.executable,str(ROOT/'monitor.py'),'collect','--max-calls',str(s.get('max_calls_per_run',5))]
  if a.send:cmd+=['--send','--max-messages','1']
  subprocess.run(cmd,check=True)
  report=json.loads((ROOT/'data/last_run.json').read_text())
  if report.get('stop_reason'):break
  if i+1<a.cycles:time.sleep(minutes*60)
