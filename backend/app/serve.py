"""Local single-worker entry point; Windows Selector loop handles SSE cancellation cleanly."""
import os
import sys
import uvicorn


if __name__=='__main__':
    uvicorn.run('app.main:app',host='127.0.0.1',port=int(os.getenv('APP_PORT','8000')),
                loop='asyncio:SelectorEventLoop' if sys.platform=='win32' else 'auto')
