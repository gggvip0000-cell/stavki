import sys; sys.argv=['x']
sys.path.insert(0,'/home/claude/stavki')
import importlib.util
spec=importlib.util.spec_from_file_location('S','/home/claude/stavki/stavki.py'); S=importlib.util.module_from_spec(spec); spec.loader.exec_module(S)
S.add_error('PARI (прямая линия): нет ответа','PARI'); S.add_error('Pinnacle: ошибка','Pinnacle'); S.add_error('что-то разовое')
print(S.STATE.status['errors'])
S.clear_error('PARI'); print(S.STATE.status['errors'])
assert not any('PARI' in e for e in S.STATE.status['errors']) and any('Pinnacle' in e for e in S.STATE.status['errors'])
S.add_error('PARI (прямая линия): 1','PARI'); S.add_error('PARI (прямая линия): 2','PARI')
assert sum('PARI' in e for e in S.STATE.status['errors'])==1
t=S.time.time; S.time.time=lambda: t()+1000; S.clear_error('нет такого')
print(S.STATE.status['errors']); assert not any('разовое' in e for e in S.STATE.status['errors'])
print('OK')
