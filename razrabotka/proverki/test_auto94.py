import sys, os, types, tempfile; sys.path.insert(0, '/home/claude/stavki'); import stavki as S
from pathlib import Path
d = tempfile.mkdtemp(); os.environ['APPDATA'] = d; S.sys = types.SimpleNamespace(platform='win32')
calls = []
def run(args, env=None, **k):
    calls.append(env['ST_TARGET']); Path(env['ST_LNK']).write_text('x'); return types.SimpleNamespace(returncode=0, stderr='', stdout='')
S.subprocess = types.SimpleNamespace(run=run)
assert S.autostart_set(True) == '' and S.autostart_path().exists() and calls[0].endswith('Stavki.bat')
assert S.autostart_set(True) == '' and len(calls) == 1          # уже есть — не пересоздаёт
assert S.autostart_set(False) == '' and not S.autostart_path().exists()
S.autostart_apply(True); assert S.STATE.status['autostart'] == {'on': True, 'want': True, 'why': ''}
print('ВСЁ ОК')
