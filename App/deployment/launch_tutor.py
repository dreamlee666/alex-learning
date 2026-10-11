import os
from pathlib import Path
_PORTABLE_DLL_DIRECTORY = os.add_dll_directory(str(Path(__file__).resolve().parents[2] / '.deployment' / 'vcruntime'))
import os
from pathlib import Path
import sys
import threading
import subprocess
import time
import atexit
import httpx
import uvicorn

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
os.environ['PATH'] = str(ROOT.parent / '.deployment' / 'tools') + os.pathsep + os.environ['PATH']
os.environ['HF_HUB_DISABLE_XET'] = '1'
os.environ['PYTHONUTF8'] = '1'
voice_child = None
try:
    voice_status = httpx.get('http://127.0.0.1:32195/health', timeout=2, trust_env=False).json()
    voice_ready = voice_status.get('app') == 'sqe-local-voice' and voice_status.get('ready')
except Exception:
    voice_ready = False
if not voice_ready:
    voice_child = subprocess.Popen([str(ROOT / '.voice-venv' / 'Scripts' / 'python.exe'),
                                    str(ROOT / 'deployment' / 'voice_server.py')],
                                   cwd=ROOT, creationflags=subprocess.CREATE_NO_WINDOW)
    (ROOT / 'deployment' / 'voice.pid').write_text(str(voice_child.pid), encoding='ascii')
    atexit.register(lambda: voice_child.terminate() if voice_child.poll() is None else None)
    for attempt in range(120):
        if voice_child.poll() is not None:
            raise RuntimeError('Local voice startup failed. See deployment/server.stderr.log.')
        try:
            voice_status = httpx.get('http://127.0.0.1:32195/health', timeout=1, trust_env=False).json()
            if voice_status.get('app') == 'sqe-local-voice' and voice_status.get('ready'):
                break
        except Exception:
            pass
        time.sleep(0.5)
    else:
        voice_child.terminate()
        raise RuntimeError('Local voice did not become ready.')
from deployment.plan_gateway import app

thread = threading.Thread(target=lambda: uvicorn.run(app, host='127.0.0.1', port=32194, log_level='warning', access_log=False), daemon=True)
thread.start()
from run_server import run
run('INFO')
