"""Portable classroom controller. Uses only the bundled Python standard library."""
import argparse
import ctypes
import hashlib
import json
import msvcrt
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
import uuid
import webbrowser
import zipfile

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / 'App'
DEP = APP / 'deployment'
PYTHON = APP / '.venv' / 'Scripts' / 'python.exe'
PORTS = (32193, 32194, 32195)
ORIGIN = 'http://127.0.0.1:32194'
LOCAL_HTTP = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def say(message):
    print(message, flush=True)


def atomic_json(path, value):
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(temp, path)


def get_json(url):
    with LOCAL_HTTP.open(url, timeout=2) as response:
        return json.load(response)


def instance_id():
    path = DEP / 'runtime.json'
    if not path.exists():
        atomic_json(path, {'gateway_key': secrets.token_urlsafe(32), 'package_instance': str(uuid.uuid4())})
    return json.loads(path.read_text(encoding='utf-8'))['package_instance']


def running_classroom():
    """Recognize an already running portable classroom without claiming ownership."""
    try:
        status = get_json(ORIGIN + '/status')
        if status.get('app') != 'sqe-english-tutor' or not status.get('package_instance'):
            return None
        voice = get_json('http://127.0.0.1:32195/health')
        with LOCAL_HTTP.open('http://127.0.0.1:32193/', timeout=2) as response:
            if response.status == 200 and voice.get('app') == 'sqe-local-voice' and voice.get('ready'):
                return status
    except Exception:
        pass
    return None


def is_ready():
    status = running_classroom()
    path = DEP / 'runtime.json'
    if not status or not path.exists():
        return False
    return status.get('package_instance') == json.loads(path.read_text(encoding='utf-8'))['package_instance']


def download(item, target):
    """Download a pinned artifact; verify before extracting or executing anything."""
    request = urllib.request.Request(item['url'], headers={'User-Agent': 'SQE-Classroom/0.1'})
    digest = hashlib.sha256()
    transferred = 0
    last_report = -1
    temp = target.with_suffix('.part')
    try:
        with urllib.request.urlopen(request, timeout=30) as response, temp.open('wb') as stream:
            if not response.geturl().startswith('https://'):
                raise RuntimeError('下载来源没有使用 HTTPS。')
            while chunk := response.read(1024 * 1024):
                transferred += len(chunk)
                if transferred > item['max_bytes']:
                    raise RuntimeError('下载文件超过预期大小。')
                stream.write(chunk)
                digest.update(chunk)
                progress = transferred // (10 * 1024 * 1024)
                if progress != last_report:
                    say('正在下载 ' + item['name'] + '：' + str(transferred // (1024 * 1024)) + ' MB')
                    last_report = progress
        if digest.hexdigest() != item['sha256']:
            raise RuntimeError('下载校验失败，请重试；没有使用该文件。')
        os.replace(temp, target)
    finally:
        temp.unlink(missing_ok=True)


def prepare_downloads(ffmpeg_archive=None):
    items = json.loads((ROOT / 'launcher' / 'downloads.json').read_text(encoding='utf-8'))
    scratch = ROOT / '.deployment' / 'downloads'
    scratch.mkdir(parents=True, exist_ok=True)
    for item in items:
        if item['name'] == 'FFmpeg':
            destination = ROOT / '.deployment' / 'tools'
            ready_file = destination / 'ffmpeg.exe'
        elif item['name'] == 'VCRuntime':
            destination = ROOT / '.deployment' / 'vcruntime'
            ready_file = destination / 'msvcp140_1.dll'
        else:
            destination = APP / '.voice-venv' / 'Lib' / 'site-packages'
            ready_file = destination / 'espeakng_loader' / 'espeak-ng.dll'
        marker = scratch / (item['name'] + '.installed.json')
        if ready_file.exists() and marker.exists():
            saved = json.loads(marker.read_text(encoding='utf-8'))
            if saved.get('artifact_sha256') == item['sha256'] and saved.get('installed_sha256') == hashlib.sha256(ready_file.read_bytes()).hexdigest():
                continue
        say('首次运行：准备 ' + item['name'] + '。需要网络，请稍候。')
        archive = scratch / item['filename']
        supplied = Path(ffmpeg_archive) if ffmpeg_archive and item['name'] == 'FFmpeg' else None
        if supplied and hashlib.sha256(supplied.read_bytes()).hexdigest() == item['sha256']:
            shutil.copyfile(supplied, archive)
        if not archive.exists() or hashlib.sha256(archive.read_bytes()).hexdigest() != item['sha256']:
            download(item, archive)
        destination.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(archive) as bundle:
            if item['name'] == 'FFmpeg':
                # Do not extract arbitrary archive paths.
                for entry in bundle.infolist():
                    relative = Path(entry.filename)
                    if relative.name not in {'ffmpeg.exe', 'LICENSE', 'README.txt'} or entry.is_dir():
                        continue
                    if relative.name == 'ffmpeg.exe' and relative.parent.name != 'bin':
                        continue
                    (destination / relative.name).write_bytes(bundle.read(entry))
            elif item['name'] == 'VCRuntime':
                for entry in bundle.infolist():
                    if '/' not in entry.filename and '\\' not in entry.filename and entry.filename.endswith('.dll'):
                        (destination / entry.filename).write_bytes(bundle.read(entry))
            else:
                for entry in bundle.infolist():
                    parts = entry.filename.split('/')
                    if parts[0] != 'espeakng_loader' or len(parts) < 2 or entry.is_dir():
                        continue
                    if any(part in {'', '.', '..'} for part in parts) or '\\' in entry.filename or ':' in entry.filename:
                        raise RuntimeError('下载包内的路径校验失败。')
                    if parts[1] not in {'espeak-ng.dll', 'espeak-ng-data'}:
                        continue
                    output = destination.joinpath(*parts)
                    if not output.resolve().is_relative_to(destination.resolve()):
                        raise RuntimeError('下载包内的路径越界。')
                    output.parent.mkdir(parents=True, exist_ok=True)
                    output.write_bytes(bundle.read(entry))
        if not ready_file.exists():
            raise RuntimeError('依赖包缺少必要文件。')
        atomic_json(marker, {'artifact_sha256': item['sha256'], 'installed_sha256': hashlib.sha256(ready_file.read_bytes()).hexdigest()})
        archive.unlink(missing_ok=True)


def initialize(ffmpeg_archive=None):
    if ctypes.sizeof(ctypes.c_void_p) != 8:
        raise RuntimeError('此版本需要 64 位 Windows。')
    instance_id()
    say('正在准备独立的课堂运行环境……')
    for name in ('.venv', '.voice-venv'):
        # Absolute paths are rewritten on every start, so a moved folder works.
        (APP / name / 'pyvenv.cfg').write_text(
            'home = ' + str(ROOT / 'runtime' / 'python') + '\n'
            'implementation = CPython\nversion_info = 3.12.14\n'
            'include-system-site-packages = false\n', encoding='utf-8')
    prepare_downloads(ffmpeg_archive)
    if not (APP / 'conf.yaml').exists():
        result = subprocess.run([str(PYTHON), str(DEP / 'configure.py')], cwd=APP,
                                capture_output=True, text=True, encoding='utf-8',
                                creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode:
            (DEP / 'initialize-error.log').write_text(result.stderr, encoding='utf-8')
            raise RuntimeError('课堂配置失败，请查看 initialize-error.log。')


def stop():
    # CIM returns Unicode using the active code page; explicitly emit UTF-8.
    for name, script in [('voice.pid', 'voice_server.py'), ('tutor.pid', 'launch_tutor.py')]:
        path = DEP / name
        if not path.exists():
            continue
        try:
            pid = int(path.read_text(encoding='ascii').strip())
            launcher = DEP / script
            query = "[Console]::OutputEncoding=[Text.Encoding]::UTF8; $p=Get-CimInstance Win32_Process -Filter 'ProcessId = " + str(pid) + "'; if($p){$p.CommandLine}"
            result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', query],
                                    capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
            if str(launcher).casefold() in result.stdout.decode('utf-8-sig', errors='ignore').casefold():
                kernel = ctypes.WinDLL('kernel32', use_last_error=True)
                kernel.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
                kernel.OpenProcess.restype = ctypes.c_void_p
                kernel.TerminateProcess.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
                kernel.CloseHandle.argtypes = [ctypes.c_void_p]
                handle = kernel.OpenProcess(1, False, pid)
                if handle:
                    kernel.TerminateProcess(handle, 0)
                    kernel.CloseHandle(handle)
        finally:
            path.unlink(missing_ok=True)
    existing = running_classroom()
    if existing:
        say('当前文件夹的服务已停止；另一份课堂仍在运行。请用原启动窗口停止它。')
    else:
        say('本软件的课堂服务已停止。')


def start(open_browser=False, ffmpeg_archive=None):
    existing = running_classroom()
    if existing:
        say('课堂已经运行。' if is_ready() else '检测到另一份便携课堂正在运行，直接打开现有课堂；登录、教材和进度继续沿用。')
        if open_browser:
            webbrowser.open(ORIGIN + '/study')
        return
    # Only clean up processes verifiably belonging to this exact package folder.
    stop()
    for port in PORTS:
        with socket.socket() as test_socket:
            try:
                test_socket.bind(('127.0.0.1', port))
            except OSError:
                raise RuntimeError('端口 ' + str(port) + ' 正被其他程序使用。请关闭其他便携版课堂后重试。')
    initialize(ffmpeg_archive)
    env = os.environ.copy()
    env.update(PYTHONUTF8='1', PYTHONIOENCODING='utf-8', PYTHONDONTWRITEBYTECODE='1', HF_HUB_OFFLINE='1')
    say('正在启动虚拟老师、语音和学习空间……')
    with (DEP / 'server.stdout.log').open('w', encoding='utf-8') as out, (DEP / 'server.stderr.log').open('w', encoding='utf-8') as err:
        child = subprocess.Popen([str(PYTHON), str(DEP / 'launch_tutor.py')], cwd=APP, env=env,
                                 stdout=out, stderr=err, creationflags=subprocess.CREATE_NO_WINDOW)
    (DEP / 'tutor.pid').write_text(str(child.pid), encoding='ascii')
    for attempt in range(180):
        if child.poll() is not None:
            stop()
            raise RuntimeError('启动失败。请点击“查看日志”，检查 server.stderr.log。')
        if is_ready():
            say('课堂已就绪。首次使用请在“账号与声音设置”连接自己的账号。')
            if open_browser:
                webbrowser.open(ORIGIN + '/study')
            return
        time.sleep(1)
    stop()
    raise RuntimeError('启动超时，请查看日志后重试。')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--start', action='store_true')
    parser.add_argument('--stop', action='store_true')
    parser.add_argument('--initialize', action='store_true')
    parser.add_argument('--open', action='store_true')
    parser.add_argument('--ffmpeg-archive', help='Use an already downloaded, verified upstream archive.')
    args = parser.parse_args()
    os.environ.update(PYTHONUTF8='1', PYTHONIOENCODING='utf-8', PYTHONDONTWRITEBYTECODE='1')
    with (ROOT / 'launcher' / '.startup.lock').open('a+b') as lock:
        lock.seek(0)
        lock.write(b'0')
        lock.flush()
        lock.seek(0)
        try:
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            raise RuntimeError('课堂正在启动，请稍候再操作。')
        if args.stop:
            stop()
        elif args.initialize:
            initialize(args.ffmpeg_archive)
        else:
            start(args.open, args.ffmpeg_archive)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        say('错误：' + str(error))
        sys.exit(1)
