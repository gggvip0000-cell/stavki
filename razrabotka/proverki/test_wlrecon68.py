"""Проверка -68: разведка страницы матча Винлайна — все рынки матча и текст страницы в отчёт, без нажатий."""
exec(open('/home/claude/bet/test_winline42.py', encoding='utf-8').read().split('c.feeds.append(f)')[0])
evs_all = [e for e in f.line.football(live=False) if e.get('start_ts')]
target = max(evs_all, key=lambda e: e.get('count_add_line') or 0)
clock[0] = target['start_ts'] - 5 * 3600
frames = [base64.b64decode(w['b64']) for w in W]
class WS:
    url = 'wss://wss.winline.ru/data_ng'
    def on(self, ev, cb): self.cb = cb
class PG:
    def on(self, ev, cb): self.wscb = cb
    def goto(self, url, **k):
        self.url = url; ws = WS(); self.wscb(ws)
        for fr in frames: ws.cb(fr)
    def wait_for_timeout(self, ms): pass
    def inner_text(self, sel): return open('/home/claude/bet/rw/match_text.txt', encoding='utf-8').read()
    def close(self): self.closed = True
class B:
    def new_page(self, **k): return PG()
r = S.winline_event_recon(B(), f, n=2)
for x in r['events']:
    print(x.get('teams'), x.get('league'), 'кадров', x.get('frames'), 'рынков', x.get('n_lines'), 'виды', x.get('kinds'), x.get('error'))
    print('  пример:', x.get('lines', [])[:3])
assert r['events'] and r['events'][0].get('n_lines', 0) > 0 and r['events'][0]['page_text']
import json; json.dumps(r, ensure_ascii=False)
print('ВСЁ ОК')
