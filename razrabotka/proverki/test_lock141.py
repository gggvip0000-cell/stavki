"""-141: одновременные /api/state из нескольких окон (ноутбук + телефон) — таблица бумаги без ошибок; обрыв связи окном — без
длинного текста ошибки в чёрном окне."""
import sys, json, tempfile, pathlib, time, threading, io, contextlib
sys.path.insert(0, '/home/user/stavki')
import stavki as S
S.HERE = pathlib.Path(tempfile.mkdtemp())
con = S.db_open()
r = json.load(open('/home/claude/bet/r0058/report.json', encoding='utf-8'))
for t in ('paper2', 'cand', 'ext_scores'):
    cols = [c[1] for c in con.execute(f'PRAGMA table_info({t})')]
    for x in r[t]:
        ks = [k for k in x if k in cols]
        con.execute(f"INSERT OR IGNORE INTO {t} ({','.join(ks)}) VALUES ({','.join('?' * len(ks))})", [x[k] for k in ks])
now = time.time()
for i in range(150):
    legs = [{'mid': 100 + i, 'fam': 'total', 'outcome': 'Меньше (2.5)', 'line': 2.5, 'odds': 2.0, 'fair': 1.9, 'ev': 0.06,
             'start_ts': now - 3600, 'title': f'К{i} — С{i}', 'res': [1, 0]} for _ in range(3)]
    con.execute("INSERT INTO expr (created, size, bookmaker, legs, odds, ev_prod, status, mult, kind) VALUES (?,3,'Олимп',?,8,0.19,'выигрыш',8,?)",
                (now - i, json.dumps(legs, ensure_ascii=False), 'ЭА' if i % 2 else 'ЭБ'))
con.commit()
S.STATS_DB = S.db_connect(check_same_thread=False); S.STATS_STAKE = 100
def hammer(fn, n_threads=6, n=12):
    errs = []
    def run():
        for _ in range(n):
            try:
                fn()
            except Exception as e:
                errs.append(str(e)[:80])
    ts = [threading.Thread(target=run) for _ in range(n_threads)]
    [t.start() for t in ts]; [t.join() for t in ts]
    return errs
old = hammer(lambda: S.paper_stats(S.STATS_DB, 100))
print('как было (одна связь, без очереди): ошибок', len(old), set(old))
def fresh():
    S.PAPER_CACHE['v'] = None
    return S.paper_cached()
new = hammer(fresh)
print('теперь: ошибок', len(new))
assert not new
assert S.paper_cached() is S.paper_cached()            # в течение 2 с — один и тот же расчёт для всех окон
# обрыв связи окном — тихо
srv = S.QuietServer(('127.0.0.1', 0), S.Handler)
buf = io.StringIO()
with contextlib.redirect_stderr(buf):
    try:
        raise ConnectionAbortedError(10053, 'разорвала подключение')
    except ConnectionAbortedError:
        srv.handle_error(None, ('127.0.0.1', 1))
    try:
        raise ValueError('настоящая ошибка')
    except ValueError:
        srv.handle_error(None, ('127.0.0.1', 1))
out = buf.getvalue(); srv.server_close()
assert 'ConnectionAbortedError' not in out and 'настоящая ошибка' in out, out[:300]
print('ВСЁ ОК' + (' (старая беда воспроизведена)' if old else ' (старая беда здесь не воспроизвелась)'))
