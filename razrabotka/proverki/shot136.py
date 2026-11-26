import sys, json, tempfile, pathlib, time
sys.path.insert(0, '/home/user/stavki')
import stavki as S
S.HERE = pathlib.Path(tempfile.mkdtemp())
con = S.db_open()
r = json.load(open('/home/claude/bet/r0058/report.json', encoding='utf-8'))
cols = [c[1] for c in con.execute('PRAGMA table_info(paper2)')]
for x in r['paper2']:
    ks = [k for k in x if k in cols]
    con.execute(f"INSERT INTO paper2 ({','.join(ks)}) VALUES ({','.join('?'*len(ks))})", [x[k] for k in ks])
now = time.time()
for i in range(25):                                    # 25 купонов — окно с прокруткой
    legs = [{'mid': 100 + 3 * i + j, 'fam': 'total', 'outcome': 'Меньше (2.5)', 'line': 2.5, 'odds': 2.0, 'fair': 1.9, 'ev': 0.06,
             'start_ts': now + 3600 + i * 60, 'title': f'Команда {i}{j} — Соперник {i}{j}', 'url': ''} for j in range(3)]
    con.execute('INSERT INTO expr (created, size, bookmaker, legs, odds, ev_prod, status, kind) VALUES (?,?,?,?,?,?,?,?)',
                (now - i * 600, 3, 'Олимп', json.dumps(legs, ensure_ascii=False), 8.0, 0.19, 'open', 'ЭА'))
con.commit()
def state():
    st = S.STATE.snapshot(); st['paper'] = S.paper_stats(con, 100); return st
ST = {'s': json.dumps(state(), ensure_ascii=False)}
from playwright.sync_api import sync_playwright
page_html = S.PAGE.replace('__VERSION__', S.VERSION)
with sync_playwright() as p:
    br = p.chromium.launch(executable_path='/opt/pw-browsers/chromium')
    for w in (1280, 390):
        pg = br.new_page(viewport={'width': w, 'height': 800})
        pg.add_init_script("try{localStorage.setItem('pview3','ЭА')}catch(e){}")
        pg.route('**/api/**', lambda rt: rt.fulfill(status=200, content_type='application/json', body='{}'))
        pg.route('**/api/state*', lambda rt: rt.fulfill(status=200, content_type='application/json', body=ST['s']))
        pg.route('http://x/', lambda rt: rt.fulfill(status=200, content_type='text/html; charset=utf-8', body=page_html))
        errs = []; pg.on('pageerror', lambda e: errs.append(str(e)))
        pg.goto('http://x/'); pg.wait_for_timeout(1500)
        pg.click('[data-epop="all"]'); pg.wait_for_timeout(500)
        pg.evaluate("document.querySelector('#pop .mbody').scrollTop=900")
        s0 = pg.evaluate("document.querySelector('#pop .mbody').scrollTop")
        pg.wait_for_timeout(7000)                     # два-три самообновления без изменений
        s1 = pg.evaluate("document.querySelector('#pop .mbody').scrollTop")
        # изменение: один купон рассчитан — окно перерисуется, прокрутка должна остаться
        con.execute("UPDATE expr SET status='проигрыш', mult=0, settled=? WHERE id=1", (time.time(),)); con.commit()
        ST['s'] = json.dumps(state(), ensure_ascii=False)
        pg.wait_for_timeout(4000)
        s2 = pg.evaluate("document.querySelector('#pop .mbody').scrollTop")
        lost = pg.evaluate("document.querySelector('#pop').innerText.includes('купон проиграл')")
        print(w, 'прокрутка: было', s0, '→ после обновлений', s1, '→ после изменения', s2, '| изменение видно:', lost, '| ошибки', errs[:2])
        assert s0 == s1 == s2 and s0 > 0 and lost
        # то же для обычного окна ставок
        pg.click('.mx'); pg.wait_for_timeout(300); pg.click('.pvb:nth-child(1)'); pg.wait_for_timeout(1200)
        pg.click('[data-pop="*|*|all"]'); pg.wait_for_timeout(500)
        pg.evaluate("document.querySelector('#pop .mbody').scrollTop=1500")
        b0 = pg.evaluate("document.querySelector('#pop .mbody').scrollTop"); pg.wait_for_timeout(7000)
        b1 = pg.evaluate("document.querySelector('#pop .mbody').scrollTop")
        print('   окно ставок: прокрутка', b0, '→', b1)
        assert b0 == b1 and b0 > 0
        # новое открытие — сверху
        pg.click('.mx'); pg.wait_for_timeout(300); pg.click('[data-pop="*|*|all"]'); pg.wait_for_timeout(400)
        assert pg.evaluate("document.querySelector('#pop .mbody').scrollTop") == 0
        con.execute("UPDATE expr SET status='open', mult=NULL WHERE id=1"); con.commit(); ST['s'] = json.dumps(state(), ensure_ascii=False)
        pg.close()
    br.close()
print('ВСЁ ОК')
