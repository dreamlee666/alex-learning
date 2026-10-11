"""Build a sanitized Windows portable copy; never copy user state or credentials.

Run with the project's main virtualenv Python. Existing deployment is untouched.
"""
import argparse
from email.parser import Parser
import hashlib
import html
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import urllib.request
import zipfile

SOURCE = Path(__file__).resolve().parents[2]
PACKAGING = Path(__file__).resolve().parent
VERSION = '0.4.1'
NAME = 'Alex-Learning'
BASE_PYTHON = Path(sys.base_prefix)
RELEASE = SOURCE.parent / 'release'
DEST = RELEASE / (NAME + '-' + VERSION)
APP = DEST / 'App'


def ignore(directory, names):
    skip = {'__pycache__', '.git', '.DS_Store', 'tests', 'test', 'site-packages', 'direct_url.json'}
    # No unused PyTorch / bundled FFmpeg binary. eSpeak NG is fetched by the recipient.
    if Path(directory).name == 'site-packages':
        skip = (skip - {'site-packages'}) | {'torch', 'functorch', 'torchgen'}
        skip.update(name for name in names if name.startswith(('torch-', 'torchgen-', 'functorch-')))
    if Path(directory).name == 'imageio_ffmpeg':
        skip.add('binaries')
    if Path(directory).name == 'espeakng_loader':
        skip |= {'espeak-ng.dll', 'espeak-ng-data'}
    return [name for name in names if name in skip or name.endswith(('.pyc', '.pyo', '.log', '.pid'))]


def copy_tree(source, dest):
    shutil.copytree(source, dest, ignore=ignore, dirs_exist_ok=True)


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding='utf-8')


def fetch(url):
    request = urllib.request.Request(url, headers={'User-Agent': 'SQE-Classroom-Build/0.1'})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


def licenses():
    target = DEST / 'licenses'
    target.mkdir(exist_ok=True)
    for name in ('LICENSE', 'LICENSE-Live2D.md'):
        shutil.copyfile(SOURCE / name, target / name)
    sources = {
        'Open-LLM-VTuber-Web-LICENSE.txt': 'https://raw.githubusercontent.com/Open-LLM-VTuber/Open-LLM-VTuber-Web/main/LICENSE',
        'Kokoro-LICENSE.txt': 'https://www.apache.org/licenses/LICENSE-2.0.txt',
        'Whisper-LICENSE.txt': 'https://raw.githubusercontent.com/openai/whisper/main/LICENSE',
        'espeakng-loader-LICENSE.txt': 'https://raw.githubusercontent.com/thewh1teagle/espeakng-loader/main/LICENSE',
        'GPL-3.0.txt': 'https://raw.githubusercontent.com/espeak-ng/espeak-ng/1.52.0/COPYING',
        'uv-redirector-LICENSE-MIT.txt': 'https://raw.githubusercontent.com/astral-sh/uv/main/LICENSE-MIT',
        'uv-redirector-LICENSE-APACHE.txt': 'https://raw.githubusercontent.com/astral-sh/uv/main/LICENSE-APACHE',
    }
    records = []
    for name, url in sources.items():
        print('Fetching license: ' + name, flush=True)
        content = fetch(url)
        (target / name).write_bytes(content)
        records.append({'file': name, 'url': url, 'sha256': hashlib.sha256(content).hexdigest()})
    write(target / 'license-sources.json', json.dumps(records, ensure_ascii=False, indent=2))
    inventories = []
    for venv in ('.venv', '.voice-venv'):
        site = APP / venv / 'Lib' / 'site-packages'
        for meta in sorted(site.glob('*.dist-info/METADATA')):
            value = Parser().parsestr(meta.read_text(encoding='utf-8', errors='replace'))
            inventories.append({'environment': venv, 'name': value.get('Name'), 'version': value.get('Version'),
                                'license': value.get('License'), 'license_expression': value.get('License-Expression'),
                                'metadata': str(meta.relative_to(DEST)).replace('\\', '/')})
    write(target / 'python-components.json', json.dumps(inventories, ensure_ascii=False, indent=2))
    write(target / 'MODELS.md', '''# Bundled models

- Kokoro-82M: Apache-2.0, original https://huggingface.co/hexgrad/Kokoro-82M ; ONNX mirror https://huggingface.co/fastrtc/kokoro-onnx , revision 8d07950c9b6c87ce6809e9bba7bd494336217c2a. File hashes: App/models/kokoro/provenance.json.
- Whisper small / faster-whisper-small: MIT, https://huggingface.co/Systran/faster-whisper-small , revision 536b0662742c02347bc0e980a01041f333bce120. File hash: App/deployment/asr-model-provenance.json.
- Silero VAD in the upstream browser frontend: MIT, https://github.com/snakers4/silero-vad . The classroom's active ASR is faster-whisper; upstream browser voice detection files are retained with the frontend.
- Live2D Mao original sample: Live2D Free Material License and Core SDK proprietary license; see LICENSE-Live2D.md. Not MIT and not licensed under the model licenses above.
''')
    write(target / 'THIRD-PARTY.md', '''# Third-party notices

Open-LLM-VTuber is MIT. The Web frontend is MIT. Local classroom additions and launcher source are MIT; copyright 2026 SQE Classroom contributors. License text: LICENSE. Python retains its own LICENSE.txt. Installed package metadata and license files are retained in each virtualenv's Lib/site-packages/*.dist-info. Inventory: python-components.json.

Live2D Cubism Core: https://www.live2d.com/eula/live2d-proprietary-software-license-agreement_en.html . Original sample Mao: https://www.live2d.com/eula/live2d-free-material-license-agreement_en.html . SDK release terms: https://www.live2d.com/en/sdk/license/ . The release fixes the supplied character; adding an avatar expansion feature changes the license analysis. Preserve the original notices. This project is not affiliated with Live2D Inc.

This content uses sample data owned and copyrighted by Live2D Inc. The sample data are utilized in accordance with terms and conditions set by Live2D Inc. This content itself is created at the author's sole discretion.

FFmpeg is NOT redistributed inside this ZIP. First launch downloads a pinned Gyan.dev GPLv3 build directly from upstream, verifies SHA256, and preserves its LICENSE and README with the installed executable. Build: https://github.com/GyanD/codexffmpeg/releases/tag/9.0.2 ; FFmpeg source: https://github.com/FFmpeg/FFmpeg/tree/946fcce07b . Gyan build information: https://www.gyan.dev/ffmpeg/builds/ . The build includes librubberband for the selected youthful voice.

eSpeak NG native DLL and voice data are NOT redistributed inside this ZIP. First launch downloads the pinned espeakng-loader 0.2.4 Windows wheel from PyPI and verifies SHA256; native component version 1.52.0 is GPLv3. Corresponding source: https://github.com/espeak-ng/espeak-ng/tree/1.52.0 ; loader source/build: https://github.com/thewh1teagle/espeakng-loader . Loader itself is MIT. GPL-3.0.txt is included for reference. Python phonemizer-fork source and license are retained in the voice environment; no modified phonemizer source is used.

Other native libraries retain upstream licenses and notices in their package metadata. PyAV/FFmpeg LGPL components: https://github.com/PyAV-Org/PyAV and https://github.com/PyAV-Org/pyav-wheels ; Python source and installation metadata are included. Libraries can be replaced in the unpacked package. No user documents or commercial SQE textbooks are included.

Microsoft VCLibs is downloaded directly from Microsoft, SHA256 verified, and used only as app-local DLLs, without system-wide registration. Official source: https://learn.microsoft.com/en-us/troubleshoot/developer/visualstudio/cpp/libraries/c-runtime-packages-desktop-bridge . It is not redistributed inside this ZIP.

OpenAI account flow: https://developers.openai.com/siwc/token-sharing-open-source . Each user grants their own account permission; no account token is bundled.
''')


def build(continue_build=False):
    if DEST.exists() and not continue_build:
        raise RuntimeError('Destination already exists. Do not overwrite an in-use package: ' + str(DEST))
    if continue_build and any((DEST / name).exists() for name in ('Alex-Learning.exe', 'App/conf.yaml', 'App/deployment/runtime.json')):
        raise RuntimeError('Only an unfinished, never-initialized build may be continued.')
    DEST.mkdir(parents=True, exist_ok=True)
    print('Copying Python runtime and selected dependencies…', flush=True)
    runtime = DEST / 'runtime' / 'python'
    runtime.mkdir(parents=True, exist_ok=True)
    for name in ('python.exe', 'pythonw.exe', 'python312.dll', 'python3.dll', 'vcruntime140.dll', 'vcruntime140_1.dll', 'LICENSE.txt'):
        shutil.copyfile(BASE_PYTHON / name, runtime / name)
    for name in ('Lib', 'DLLs'):
        copy_tree(BASE_PYTHON / name, runtime / name)
    for venv in ('.venv', '.voice-venv'):
        scripts = APP / venv / 'Scripts'
        scripts.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(SOURCE / venv / 'Scripts' / 'python.exe', scripts / 'python.exe')
        copy_tree(SOURCE / venv / 'Lib' / 'site-packages', APP / venv / 'Lib' / 'site-packages')
    print('Copying source, character, frontend and models…', flush=True)
    for name in ('src', 'prompts', 'upgrade_codes', 'config_templates', 'frontend', 'assets', 'backgrounds', 'web_tool'):
        copy_tree(SOURCE / name, APP / name)
    copy_tree(SOURCE / 'live2d-models' / 'mao_pro', APP / 'live2d-models' / 'mao_pro')
    # No sample voice recordings from the Live2D character are redistributed.
    for path in (APP / 'live2d-models').rglob('*'):
        if path.is_file() and path.suffix.lower() in {'.mp3', '.wav', '.ogg'}:
            path.unlink()
    (APP / 'avatars').mkdir(exist_ok=True)
    shutil.copyfile(SOURCE / 'avatars' / 'mao.png', APP / 'avatars' / 'mao.png')
    for name in ('cache', 'logs', 'chat_history', 'materials', 'classroom_characters'):
        (APP / name).mkdir(exist_ok=True)
    for name in ('run_server.py', 'upgrade.py', 'pyproject.toml', 'mcp_servers.json', 'model_dict.json', 'LICENSE', 'LICENSE-Live2D.md'):
        shutil.copyfile(SOURCE / name, APP / name)
    dep = APP / 'deployment'
    dep.mkdir(exist_ok=True)
    for name in ('stellaris_library.py', 'STELLARIS-GUIDE.md', 'companion.py', 'companion-ui.js', 'speech_text.py', 'COMPANION-GUIDE.md', 'IMPORT-GUIDE.md', 'providers.py', 'learning.py', 'learning_routes.py', 'learning-ui.js', 'LEARNING-REFERENCES.md', 'teaching.py', 'configure.py', 'launch_tutor.py', 'plan_gateway.py', 'voice_server.py', 'study_store.py', 'study_routes.py',
                 'study.html', 'study.js', 'import-queue.js', 'voice-turn.js', 'study.css', 'settings.html', 'voice-profile.json',
                 'installed-requirements.txt', 'voice-requirements.txt', 'study-requirements.txt', 'asr-model-provenance.json'):
        shutil.copyfile(SOURCE / 'deployment' / name, dep / name)
    copy_tree(SOURCE / 'models' / 'kokoro', APP / 'models' / 'kokoro')
    snapshot = SOURCE / 'models' / 'whisper' / 'models--Systran--faster-whisper-small' / 'snapshots' / '536b0662742c02347bc0e980a01041f333bce120'
    copy_tree(snapshot, APP / 'models' / 'whisper-small')
    # Replace local addresses in copied source only; original deployment stays live.
    for root in (APP / 'src', APP / 'deployment', APP / 'frontend', APP / 'config_templates'):
        for path in root.rglob('*'):
            if not path.is_file() or path.suffix not in {'.py', '.js', '.html', '.yaml', '.css', '.json'}:
                continue
            value = path.read_text(encoding='utf-8')
            for old, new in (('12393', '32193'), ('12394', '32194'), ('12395', '32195'), ('SQEEnglishTutor', 'SQEEnglishTutorPortable')):
                value = value.replace(old, new)
            value = value.replace('localhost:32193', '127.0.0.1:32193')
            path.write_text(value, encoding='utf-8')
    path = dep / 'configure.py'
    value = path.read_text(encoding='utf-8').replace(
        'models/whisper/models--Systran--faster-whisper-small/snapshots/536b0662742c02347bc0e980a01041f333bce120', 'models/whisper-small')
    value = value.replace('for an adult Chinese-qualified lawyer preparing', 'for an adult learner preparing')
    value = value.replace("Use the learner's Chinese-law experience for comparisons", "If the learner has Chinese-law experience, use it for comparisons")
    write(path, value)
    path = dep / 'plan_gateway.py'
    value = path.read_text(encoding='utf-8').replace("'app': 'sqe-english-tutor', 'connected':", "'app': 'sqe-english-tutor', 'package_instance': json.loads(RUNTIME.read_text(encoding='utf-8'))['package_instance'], 'connected':")
    write(path, value)
    path = dep / 'launch_tutor.py'
    value = path.read_text(encoding='utf-8').replace('timeout=2).json()', 'timeout=2, trust_env=False).json()').replace('timeout=1).json()', 'timeout=1, trust_env=False).json()').replace('range(40)', 'range(120)')
    write(path, value)
    dll_setup = "import os\nfrom pathlib import Path\n_PORTABLE_DLL_DIRECTORY = os.add_dll_directory(str(Path(__file__).resolve().parents[2] / '.deployment' / 'vcruntime'))\n"
    for filename in ('launch_tutor.py', 'voice_server.py'):
        path = dep / filename
        write(path, dll_setup + path.read_text(encoding='utf-8'))
    path = APP / 'src' / 'open_llm_vtuber' / 'live2d_model.py'
    value = path.read_text(encoding='utf-8').replace('        self.model_info: dict = self._lookup_model_info(model_name)',
        '        if model_name != "mao_pro":\n            raise ValueError("This portable edition uses the fixed Mao character.")\n        self.model_info: dict = self._lookup_model_info(model_name)')
    write(path, value)
    path = APP / 'run_server.py'
    write(path, path.read_text(encoding='utf-8').replace('diagnose=True', 'diagnose=False'))
    # Preserve OSS sources used by the direct account flow and enable rebuilding.
    copy_tree(PACKAGING, DEST / 'launcher')
    write(DEST / 'launcher' / 'BUILDING.md', 'Build from the existing source deployment using deployment/packaging/build_portable.py. Install the recorded main and voice requirements into their separate environments and obtain the pinned model revisions. Run with the main environment Python. The builder copies a whitelist, excludes state, bundles Python from sys.base_prefix, and compiles Launcher.cs with the Windows .NET Framework compiler. --zip creates the clean release archive. The bundled App directory is the corresponding classroom source; the upstream frontend build is available from Open-LLM-VTuber/Open-LLM-VTuber-Web.\n')
    e_data = json.loads(fetch('https://pypi.org/pypi/espeakng-loader/0.2.4/json'))
    wheel = next(item for item in e_data['urls'] if item['filename'].endswith('win_amd64.whl'))
    downloads = [
        {'name': 'FFmpeg', 'filename': 'ffmpeg-9.0.2-essentials_build.zip',
         'url': 'https://github.com/GyanD/codexffmpeg/releases/download/9.0.2/ffmpeg-9.0.2-essentials_build.zip',
         'sha256': '60f467265b1e312373dbcd92200c2618a74850f98d3d078e94296bb3fa2047ba', 'max_bytes': 250 * 1024 * 1024},
        {'name': 'eSpeakNG', 'filename': wheel['filename'], 'url': wheel['url'],
         'sha256': wheel['digests']['sha256'], 'max_bytes': 60 * 1024 * 1024},
        {'name': 'VCRuntime', 'filename': 'Microsoft.VCLibs.x64.14.00.Desktop.appx',
         'url': 'https://download.microsoft.com/download/4/7/c/47c6134b-d61f-4024-83bd-b9c9ea951c25/Microsoft.VCLibs.x64.14.00.Desktop.appx',
         'sha256': 'b56a9101f706f9d95f815f5b7fa6efbac972e86573d378b96a07cff5540c5961', 'max_bytes': 15 * 1024 * 1024},
    ]
    write(DEST / 'launcher' / 'downloads.json', json.dumps(downloads, ensure_ascii=False, indent=2))
    licenses()
    readme = (PACKAGING / 'README.md').read_text(encoding='utf-8')
    write(DEST / '使用说明.md', readme)
    write(DEST / '使用说明.html', '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>Alex · 使用说明</title><style>body{max-width:900px;margin:40px auto;padding:0 24px;background:#faf8f4;color:#222;font:16px/1.8 "Microsoft YaHei",sans-serif}pre{white-space:pre-wrap;font:inherit}</style><pre>' + html.escape(readme) + '</pre></html>')
    csc = Path(os.environ['WINDIR']) / 'Microsoft.NET' / 'Framework64' / 'v4.0.30319' / 'csc.exe'
    subprocess.run([str(csc), '/nologo', '/target:winexe', '/platform:x64', '/optimize+',
                    '/r:System.Windows.Forms.dll', '/r:System.Drawing.dll',
                    '/out:' + str(DEST / 'Alex-Learning.exe'), str(DEST / 'launcher' / 'Launcher.cs')], check=True)
    subprocess.run([str(csc), '/nologo', '/target:winexe', '/platform:x64', '/optimize+', '/r:System.Windows.Forms.dll', '/r:System.Drawing.dll', '/r:System.Web.Extensions.dll', '/out:' + str(DEST / 'Alex-Game-Companion.exe'), str(DEST / 'launcher' / 'GameCompanion.cs')], check=True)
    write(DEST / '停止课堂.cmd', '@echo off\n"%~dp0runtime\\python\\python.exe" -X utf8 "%~dp0launcher\\bootstrap.py" --stop\npause\n')
    size = sum(p.stat().st_size for p in DEST.rglob('*') if p.is_file())
    write(DEST / 'package-manifest.json', json.dumps({'name': 'Alex Learning Portable', 'version': VERSION,
           'platform': 'windows-x64', 'ports': [32193, 32194, 32195], 'user_data': '%LOCALAPPDATA%/SQEEnglishTutorPortable',
           'bundled_bytes': size, 'external_credentials_bundled': False, 'commercial_textbooks_bundled': False,
           'first_run_downloads': ['FFmpeg 9.0.2', 'eSpeak NG 1.52.0 (espeakng-loader 0.2.4)', 'Microsoft VCLibs x64']}, ensure_ascii=False, indent=2))
    print(json.dumps({'folder': str(DEST), 'bytes': size}, ensure_ascii=False), flush=True)


def archive(refresh=False):
    # Refuse to share a package that was already used, rather than guessing private data.
    prohibited = [APP / 'deployment' / 'runtime.json', APP / 'conf.yaml']
    for path in prohibited:
        if path.exists():
            raise RuntimeError('Build a fresh copy before sharing; initialized package found: ' + str(path))
    output = RELEASE / (NAME + '-Windows-' + VERSION + '.zip')
    if output.exists() and not refresh:
        raise RuntimeError('Archive already exists: ' + str(output))
    archive_path = output.with_suffix('.zip.partial') if refresh else output
    print('Creating sharing ZIP…', flush=True)
    with zipfile.ZipFile(archive_path, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=1, allowZip64=True) as bundle:
        for path in sorted(DEST.rglob('*')):
            if path.is_file():
                bundle.write(path, str(path.relative_to(RELEASE)))
            elif not any(path.iterdir()):
                bundle.write(path, str(path.relative_to(RELEASE)) + '/')
    if refresh:
        os.replace(archive_path, output)
    digest = hashlib.sha256()
    with output.open('rb') as stream:
        while data := stream.read(4 * 1024 * 1024):
            digest.update(data)
    write(output.with_suffix('.zip.sha256'), digest.hexdigest() + '  ' + output.name + '\n')
    print(json.dumps({'zip': str(output), 'bytes': output.stat().st_size, 'sha256': digest.hexdigest()}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--zip', action='store_true')
    parser.add_argument('--archive-only', action='store_true')
    parser.add_argument('--continue-build', action='store_true', help='Resume an unfinished build that has never been initialized.')
    parser.add_argument('--refresh-archive', action='store_true', help='Replace an existing clean archive atomically after fixes.')
    args = parser.parse_args()
    if not args.archive_only:
        build(args.continue_build)
    if args.zip or args.archive_only:
        archive(args.refresh_archive)
