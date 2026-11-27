"""-143: сайт конторы не открылся при запуске — страница закрывается, новые попытки 2/4/8/10 мин (повторная ждёт 30 с),
открылся — ошибка снимается, опрос идёт; капча — без повторов."""
import sys, tempfile, pathlib
sys.path.insert(0, '/home/user/stavki')
import stavki as S
S.HERE = pathlib.Path(tempfile.mkdtemp())
T = [1795700000.0]
S.time.time = lambda: T[0]
class Page:
    closed = False
    def close(self): self.closed = True
class Feed:
    name = 'Олимп'
    def __init__(self, fails, blocked=False):
        self.left, self.page, self.calls, self.blocked0 = fails, None, [], blocked
        self.last_poll, self.fails, self.polls = 0, 0, 0
    def start(self, browser, timeout=90000):
        self.calls.append(timeout); self.page = Page(); self.lastpage = self.page
        if self.blocked0:
            self.blocked = True; raise RuntimeError('капча')
        if self.left:
            self.left -= 1; raise RuntimeError('Page.goto: Timeout 90000ms exceeded.')
    def poll(self):
        self.polls += 1; self.last_poll = T[0]
C = S.Collector.__new__(S.Collector)
C.browser = object(); C.cfg = {'direct_poll_sec': 5}; C.poll_pin = lambda: None
C.save_scores = C.fill_links = C.direct_values_for = lambda f: None
f = Feed(3); C.feeds = [f]
assert not C.feed_start(f)
p0 = f.lastpage
assert f.page is None and p0.closed and f.need_start and f.calls == [90000]
errs = lambda: [e for e in S.STATE.status.get('errors', [])] if isinstance(S.STATE.status.get('errors'), list) else S.STATE.status.get('errors')
print('ошибка:', [e for e in (S.STATE.errors if hasattr(S.STATE, 'errors') else [])][-1:] or errs())
ticks = []
for minute in range(0, 40):
    T[0] += 60
    n = len(f.calls); C.poll_feeds()
    if len(f.calls) > n:
        ticks.append(minute + 1)
print('попытки на минутах:', ticks, 'ожидания', f.calls)
assert ticks[:3] == [2, 6, 14], ticks           # 2 мин, потом 4, потом 8 — на 4-й раз открылся
assert f.calls[1:] == [30000, 30000, 30000] and not f.need_start and f.page is not None and f.polls > 0
# капча — больше не пробует
g = Feed(0, blocked=True); C.feeds = [g]
C.feed_start(g)
for _ in range(30):
    T[0] += 60; C.poll_feeds()
assert g.calls == [90000] and not g.need_start
print('ВСЁ ОК')
