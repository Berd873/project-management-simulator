"""Verify the documented local entry point with an isolated SQLite database."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

root=Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix='pm-local-smoke-') as directory:
    with socket.socket() as listener:
        listener.bind(('127.0.0.1',0))
        port=listener.getsockname()[1]
    env={**os.environ,'APP_PORT':str(port),'DATABASE_URL':'sqlite:///'+(Path(directory)/'smoke.db').as_posix()}
    with open(Path(directory)/'server.log','w+',encoding='utf-8') as log:
        process=subprocess.Popen([sys.executable,'-m','app.serve'],cwd=root,env=env,stdout=log,stderr=log,
                                 creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        base=f'http://127.0.0.1:{port}'
        def request(path,payload=None,headers=None):
            data=json.dumps(payload).encode() if payload is not None else None
            req=urllib.request.Request(base+path,data=data,headers={'Content-Type':'application/json',**(headers or {})})
            with urllib.request.urlopen(req,timeout=10) as response:
                return response.status,response.read()
        try:
            for _ in range(80):
                try:
                    assert json.loads(request('/api/v1/health')[1])['status']=='ok'
                    break
                except (OSError,urllib.error.URLError):
                    if process.poll() is not None:
                        raise RuntimeError('Local server terminated before readiness')
                    time.sleep(.2)
            else:
                raise RuntimeError('Local server readiness timeout')
            assert '项目协作实验室' in request('/')[1].decode('utf-8')
            project=json.loads(request('/api/v1/projects',{'name':'Library Management System','description':'Library catalog, readers, borrowing, returns and search.','llm_mode':'mock','sponsor_mode':'llm','seed':42})[1])
            req=urllib.request.Request(base+f"/api/v1/projects/{project['id']}/delivery",data=b'',headers={'Idempotency-Key':'local-smoke'})
            with urllib.request.urlopen(req,timeout=10) as response:
                assert response.status==202
                run=json.load(response)['run_id']
            for _ in range(150):
                delivery=json.loads(request(f'/api/v1/runs/{run}/delivery')[1])
                if delivery['status']=='completed':
                    break
                if delivery['status']=='failed':
                    raise RuntimeError('Mock delivery failed')
                time.sleep(.2)
            else:
                raise RuntimeError('Delivery completion timeout')
            report=json.loads(request(f'/api/v1/runs/{run}/simulation/report')[1])
            assert report['accepted'] and report['report']['simulation_days']==9
            xml=request(f'/api/v1/runs/{run}/export?baseline_version=2')[1]
            assert len(ET.fromstring(xml).findall('{http://schemas.microsoft.com/project}Tasks/{http://schemas.microsoft.com/project}Task'))==5
            print('PASS: app.serve, production UI, Mock delivery, final report, MSPDI download; isolated database')
        finally:
            process.terminate()
            process.wait(timeout=10)
