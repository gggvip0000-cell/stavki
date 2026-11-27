import sys, json, tempfile, pathlib, time
sys.path.insert(0, '/home/user/stavki')
import stavki as S
S.HERE = pathlib.Path(tempfile.mkdtemp())
con = S.db_open()
now = time.time()
ins = ("INSERT INTO paper2 (strategy, src, created, match_id, title, league, start_ts, bookmaker, fam, outcome, line, odds, ev, fair, status, profit, void, settled)"
       " VALUES ('П','сайт',?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)")
con.execute(ins, (now - 9000, 1, 'Усти-над-Лабем — Ганацка Славия Кромержиж', 'Чехия: Футбольная национальная лига', now - 3 * 3600, 'PARI', 'total', 'Меньше (3)', 3.0, 1.9, 0.05, 1.81, 'open', None, None, None))
con.execute(ins, (now - 9000, 2, 'Дордрехт — Витесс', 'Голландия: 1-й дивизион', now - 2 * 3600, 'Олимп', '1x2', 'П1', None, 3.27, 0.057, 3.09, 'open', None, None, None))
con.execute(ins, (now - 9000, 3, 'Матч — Отменённый', 'Лига', now - 4 * 3600, 'PARI', 'c_tt1', 'Меньше (4.5)', 4.5, 1.9, 0.05, 1.81, 'возврат', 0, 1, now))
con.execute("INSERT INTO ext_live (match_id, ft1, ft2, c1, c2, ts, fin, note) VALUES (2,NULL,NULL,NULL,NULL,?,0,'перенесён')", (now - 600,))
con.commit()
ST = json.dumps(dict(S.STATE.snapshot(), paper=S.paper_stats(con, 100)), ensure_ascii=False)
from playwright.sync_api import sync_playwright
page_html = S.PAGE.replace('__VERSION__', S.VERSION)
out = sys.argv[1]
with sync_playwright() as p:
    br = p.chromium.launch(executable_path='/opt/pw-browsers/chromium')
    pg = br.new_page(viewport={'width': 1280, 'height': 700})
    posted = []
    pg.add_init_script("try{localStorage.setItem('pview3','П')}catch(e){}")
    pg.route('**/api/**', lambda rt: (posted.append(rt.request.post_data) if 'manual_score' in rt.request.url else None, rt.fulfill(status=200, content_type='application/json', body='{"ok":true}'))[1])
    pg.route('**/api/state*', lambda rt: rt.fulfill(status=200, content_type='application/json', body=ST))
    pg.route('http://x/', lambda rt: rt.fulfill(status=200, content_type='text/html; charset=utf-8', body=page_html))
    errs = []; pg.on('pageerror', lambda e: errs.append(str(e)))
    pg.goto('http://x/'); pg.wait_for_timeout(1500)
    pg.click('#paper .ptab tr.tot [data-pop$="|all"]'); pg.wait_for_timeout(600)
    t = pg.inner_text('#pop'); print('кнопок:', t.count('Матч не состоялся'), '| перенесён:', 'на FotMob: матч перенесён' in t, '| возврат:', 'матч не состоялся — возврат 0 ₽' in t)
    assert t.count('Матч не состоялся') == 2 and 'на FotMob: матч перенесён' in t and 'матч не состоялся — возврат 0 ₽' in t
    pg.screenshot(path=f'{out}/shot144.png')
    pg.on('dialog', lambda d: d.accept())
    pg.click('.voidb >> nth=0'); pg.wait_for_timeout(500)
    print('отправлено:', posted); assert posted and '"part":"x"' in posted[-1]
    print('ошибки', errs); assert not errs
    br.close()
print('ВСЁ ОК')
