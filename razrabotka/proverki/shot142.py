"""-142: отметки «увидено» общие для устройств: посмотрел на «телефоне» — на «ноутбуке» «+N/−N», точки вкладок и «НОВОЕ» пропадают."""
import sys, json, tempfile, pathlib, time, threading
sys.path.insert(0, '/home/user/stavki')
import stavki as S
S.HERE = pathlib.Path(tempfile.mkdtemp())
con = S.db_open()
now = time.time()
ins = ("INSERT INTO paper2 (strategy, src, created, match_id, title, league, start_ts, bookmaker, fam, outcome, line, odds, ev, fair, status)"
       " VALUES ('У','сайт',?,?,?,'Лига',?,'Олимп','c_tt2','Меньше (4.5)',4.5,1.9,0.06,1.79,'open')")
for i in range(4):
    con.execute(ins, (now - 7200, 10 + i, f'Хозяева {i} — Гости {i}', now - 1800))
legs = [{'mid': 50 + j, 'fam': 'total', 'outcome': 'Меньше (2.5)', 'line': 2.5, 'odds': 2.0, 'fair': 1.9, 'ev': 0.06,
         'start_ts': now - 1800, 'title': f'К{j} — С{j}'} for j in range(3)]
for i in range(2):
    con.execute("INSERT INTO expr (created, size, bookmaker, legs, odds, ev_prod, status, kind) VALUES (?,3,'Олимп',?,8,0.19,'open','ЭА')",
                (now - 3000 + i, json.dumps(legs, ensure_ascii=False)))
con.commit()
S.STATS_DB = S.db_connect(check_same_thread=False); S.STATS_STAKE = 100; S.PAPER_TTL = 0.1
srv = S.QuietServer(('127.0.0.1', 0), S.Handler); port = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()
URL = f'http://127.0.0.1:{port}/'
from playwright.sync_api import sync_playwright
def cells(pg):
    return pg.evaluate("[...document.querySelectorAll('#paper .ptab tr.tot td')].map(t=>t.innerText.replace(/\\s+/g,' ').trim())")
def dot(pg, i):
    return pg.evaluate(f"!!document.querySelector('.pvb:nth-child({i}) .tdot')")
out = sys.argv[1] if len(sys.argv) > 1 else '/tmp'
with sync_playwright() as p:
    br = p.chromium.launch(executable_path='/opt/pw-browsers/chromium')
    lap = br.new_context(viewport={'width': 1280, 'height': 800}).new_page()
    tel = br.new_context(viewport={'width': 390, 'height': 800}).new_page()
    errs = []
    for pg in (lap, tel):
        pg.on('pageerror', lambda e: errs.append(str(e)))
        pg.add_init_script("try{if(!localStorage.getItem('pseen3t_У'))localStorage.setItem('pseen3t_У',Date.now()-3600000)}catch(e){}")
        pg.goto(URL); pg.wait_for_timeout(2500)
    # обе ставки 1 и купон 1 рассчитались
    con.execute("UPDATE paper2 SET status='выигрыш', profit=0.9, res_h=1, res_a=2, settled=? WHERE match_id=10", (now,))
    con.execute("UPDATE expr SET status='проигрыш', mult=0, settled=? WHERE id=1", (now,)); con.commit()
    lap.wait_for_timeout(3800); tel.wait_for_timeout(500)
    c_lap, c_tel = cells(lap), cells(tel)
    print('ноутбук:', c_lap); print('телефон:', c_tel)
    assert '+1' in c_lap[2] and '+1' in c_tel[2], (c_lap, c_tel)
    print('точка на «А» — ноутбук', dot(lap, 3), 'телефон', dot(tel, 3)); assert dot(lap, 3) and dot(tel, 3)
    # на «телефоне» открыл «✓» и закрыл; открыл вкладку «А», открыл «✗» и закрыл
    tel.click('#paper .ptab tr.tot [data-pop$="|выигрыш"]'); tel.wait_for_timeout(500); tel.click('.mx'); tel.wait_for_timeout(500)
    tel.click('.pvb:nth-child(3)'); tel.wait_for_timeout(1500)
    tel.click('[data-epop="проигрыш"]'); tel.wait_for_timeout(500); tel.click('.mx'); tel.wait_for_timeout(3500)
    print('телефон после просмотра:', cells(tel))
    # «ноутбук» — сам ничего не нажимал
    lap.wait_for_timeout(7000)
    c2 = cells(lap); print('ноутбук после просмотра на телефоне:', c2, '· точка на «А»:', dot(lap, 3))
    assert '+1' not in c2[2] and not dot(lap, 3), c2
    lap.screenshot(path=f'{out}/shot142_laptop.png', clip={'x': 0, 'y': 0, 'width': 1280, 'height': 330})
    lap.click('.pvb:nth-child(3)'); lap.wait_for_timeout(1500)
    ce = cells(lap); print('ноутбук, экспрессы:', ce); assert not any(('+' in c or '−' in c) for c in ce[2:8] if c not in ('·',)) or ce[3] == '1', ce
    assert '+1' not in ce[3] and '−1' not in ce[6], ce
    # после перезапуска браузера ноутбука (новое окно) — тоже всё увидено (хранится в программе)
    lap2 = br.new_context(viewport={'width': 1280, 'height': 800}).new_page(); lap2.goto(URL); lap2.wait_for_timeout(4000)
    print('ноутбук, новое окно:', cells(lap2))
    print('ошибки', errs); assert not errs
    print('файл отметок:', (S.HERE / 'seen_sync.json').stat().st_size, 'байт')
    br.close()
srv.shutdown()
print('ВСЁ ОК')
