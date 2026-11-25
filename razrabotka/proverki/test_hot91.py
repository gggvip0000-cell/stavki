"""-91: обновление без перезапуска, если поменялось только окно; сохранение цен Pinnacle между перезапусками."""
import sys, os, shutil, tempfile, pathlib, time, io
sys.path.insert(0, '/home/claude/stavki'); import stavki as S
src = open('/home/claude/stavki/stavki.py', encoding='utf-8').read()
d = pathlib.Path(tempfile.mkdtemp()); (d / 'stavki.py').write_text(src, encoding='utf-8'); S.HERE = d
newv = S.VERSION.rsplit('-', 1)[0] + '-' + str(int(S.VERSION.rsplit('-', 1)[1]) + 1)
only_page = src.replace(f'VERSION = "{S.VERSION}"', f'VERSION = "{newv}"').replace('<title>Ставки — можно ставить сейчас</title>', '<title>ТЕСТ</title>')
code_too = only_page.replace('NDFL_RATE = 0.13', 'NDFL_RATE = 0.14')
class Resp(io.BytesIO):
    def __enter__(s): return s
    def __exit__(s, *a): pass
def serve(text): S.urllib.request.urlopen = lambda req, timeout=0: Resp(text.encode('utf-8'))
old_v = S.VERSION
serve(code_too); r1 = S.hot_update(); print('код поменялся → без перезапуска?', r1); assert r1 is False and S.VERSION == old_v
serve(only_page); r2 = S.hot_update(); print('только окно → без перезапуска?', r2, S.VERSION, '<title>ТЕСТ</title>' in S.PAGE)
assert r2 and S.VERSION == newv and '<title>ТЕСТ</title>' in S.PAGE and (d / 'stavki.py').read_text(encoding='utf-8') == only_page
assert S.STATE.status['version'] == newv
serve(only_page); assert S.hot_update() is False     # та же версия ещё раз — не новее
# цены Pinnacle
S.PIN_STATE = d / 'pin_state.pkl'
p1 = S.PinnacleFeed(); p1.fair[5] = {('1x2', None): (0.5, [2.0, 3.5, 4.0], time.time() - 30)}; p1.match_map[77] = (5, False); p1.leagues[1] = {'name': 'x', 'last': 1, 'next_start': None}
S.save_pin_state(p1)
p2 = S.PinnacleFeed(); n = S.load_pin_state(p2)
print('цен с прошлого запуска:', n, p2.match_map, 5 in p2.pending); assert n == 1 and p2.match_map[77] == (5, False) and 5 in p2.pending
assert not S.PIN_STATE.exists() and S.load_pin_state(S.PinnacleFeed()) == 0
S.save_pin_state(p1); os.utime(S.PIN_STATE, None)
import pickle; dd = pickle.loads(S.PIN_STATE.read_bytes()); dd['saved'] -= 3600; S.PIN_STATE.write_bytes(pickle.dumps(dd))
assert S.load_pin_state(S.PinnacleFeed()) == 0      # старше 15 мин — не берём
print('ВСЁ ОК')
