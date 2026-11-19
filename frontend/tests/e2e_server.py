"""Browser tests use an isolated database; never touch the user's projects or API key."""
import os
import tempfile
import sys
from pathlib import Path

import uvicorn

with tempfile.TemporaryDirectory(prefix='pm-browser-') as directory:
    os.environ['DATABASE_URL']='sqlite:///'+(Path(directory)/'browser.db').as_posix()
    uvicorn.run('app.main:app',host='127.0.0.1',port=8765,log_level='warning',
                loop='asyncio:SelectorEventLoop' if sys.platform=='win32' else 'auto')
