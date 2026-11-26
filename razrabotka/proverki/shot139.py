import sys, json, tempfile, pathlib, time
sys.path.insert(0, '/home/user/stavki')
import stavki as S
S.HERE = pathlib.Path(tempfile.mkdtemp())
con = S.db_open()
now = time.time(); st = now - 3600
ins = ("INSERT INTO paper2 (strategy, src, created, match_id, title, league, start_ts, bookmaker, fam, outcome, line, odds, ev, fair,"
       " status, profit, res_h, res_a, early, early_at, early_h, early_a, settled) VALUES ('П','сайт',?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)")
con.execute(ins, (st - 900, 1, 'Ювентус — Омония', 'Европа: Лига Европы', st, 'Олимп', 'total', 'Меньше (2.5)', 2.5, 3.04, 0.115, 2.73,
                  'проигрыш', -1, 2, 1, 1, '2-й тайм · 57-я минута', 2, 1, now))
con.execute(ins, (st - 900, 2, 'Лион — Лиллестрём', 'Европа: Лига Европы', st - 7200, 'Олимп', 'c_tt2', 'Меньше (4.5)', 4.5, 1.83, 0.051, 1.74,
                  'проигрыш', -1, 6, 3, 0, '2-й тайм · 71-я минута', 4, 5, now))
con.commit()
ST = json.dumps(dict(S.STATE.snapshot(), paper=S.paper_stats(con, 100)), ensure_ascii=False)
from playwright.sync_api import sync_playwright
page_html = S.PAGE.replace('__VERSION__', S.VERSION)
out = sys.argv[1]
with sync_playwright() as p:
    br = p.chromium.launch(executable_path='/opt/pw-browsers/chromium')
    for w in (1280, 390):
        pg = br.new_page(viewport={'width': w, 'height': 700})
        pg.add_init_script("try{localStorage.setItem('pview3','П')}catch(e){}")
        pg.route('**/api/**', lambda rt: rt.fulfill(status=200, content_type='application/json', body='{}'))
        pg.route('**/api/state*', lambda rt: rt.fulfill(status=200, content_type='application/json', body=ST))
        pg.route('http://x/', lambda rt: rt.fulfill(status=200, content_type='text/html; charset=utf-8', body=page_html))
        errs = []; pg.on('pageerror', lambda e: errs.append(str(e)))
        pg.goto('http://x/'); pg.wait_for_timeout(1500)
        pg.click('[data-pop="*|*|all"]'); pg.wait_for_timeout(600)
        t = pg.inner_text('#pop'); print(w, errs[:2])
        assert "закрыта на 57'" in t and 'итог: угловые' in t and "закрыта на 71' при 4:5" in t and not errs
        pg.screenshot(path=f'{out}/shot139_{w}.png')
        pg.close()
    br.close()
print('ВСЁ ОК')
