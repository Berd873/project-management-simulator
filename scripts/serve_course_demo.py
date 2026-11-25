"""Restore the published course replay once, then serve it without new API calls."""
from pathlib import Path
import os,sys,zipfile,runpy
root=Path(__file__).resolve().parents[1]
os.chdir(root)
sys.path.insert(0,str(root/'backend'))
out=root/'output/real-ticketing';out.mkdir(parents=True,exist_ok=True)
names=['demo.db','demo.checkpoints.db']
present=[(out/n).exists() for n in names]
if any(present) and not all(present):raise SystemExit('Incomplete replay database pair; preserve your files and restore both together.')
if not any(present):
 with zipfile.ZipFile(root/'examples/campus_ticketing/replay.zip') as z:
  assert sorted(z.namelist())==sorted(names)
  for name in names:(out/name).write_bytes(z.read(name))
os.environ['DATABASE_URL']='sqlite:///'+(out/'demo.db').as_posix()
print('Open http://127.0.0.1:8000/?run=29cf01fc-e98a-4736-9601-86e05d7139c0',flush=True)
runpy.run_module('app.serve',run_name='__main__')
