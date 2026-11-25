import sys, json, tempfile, pathlib, time
sys.path.insert(0, '/home/user/stavki')
import stavki as S
S.HERE = pathlib.Path(tempfile.mkdtemp())
con = S.db_open()
r = json.load(open('/home/claude/bet/r0058/report.json', encoding='utf-8'))
cols = [c[1] for c in con.execute('PRAGMA table_info(paper2)')]
con.execute('DELETE FROM paper2')
for x in r['paper2']:
    ks = [k for k in x if k in cols]
    con.execute(f"INSERT INTO paper2 ({','.join(ks)}) VALUES ({','.join('?'*len(ks))})", [x[k] for k in ks])
now = time.time()
def leg(mid, title, fam, oc, ln, odds, st, res=None, clv=None):
    d = {'fair': round(odds / 1.06, 3), 'mid': mid, 'fam': fam, 'outcome': oc, 'line': ln, 'odds': odds, 'ev': 0.06, 'start_ts': st, 'title': title, 'url': 'https://olimp.bet/x'}
    if res: d['res'] = res
    if clv is not None: d['clv'] = clv
    return d
E = [('ЭА', [leg(1, 'Лион — Бетис', 'total', 'Меньше (2.5)', 2.5, 2.05, now - 9000, [1, 0], 0.06), leg(2, 'Порту — Ницца', '1x2', 'П2', None, 3.4, now - 8000, [2, 2], 0.04), leg(3, 'Фенербахче — Брага', 'c_tt1', 'Меньше (5.5)', 5.5, 1.9, now - 9000, [4, 6], 0.07)], 'проигрыш', 0.0),
     ('ЭА', [leg(4, 'Рома — Мидтьюлланд', 'total', 'Больше (2.5)', 2.5, 1.95, now + 3600), leg(5, 'Сельтик — Утрехт', 'ah', 'Ф2 (+0.5)', -0.5, 2.1, now + 5000), leg(6, 'Бранн — Фрайбург', 'h1_1x2', 'П2', None, 3.2, now + 5400)], 'open', None),
     ('ЭБ', [leg(7, 'Бенфика — Наполи', '1x2', 'П1', None, 2.6, now - 9000, [2, 1], 0.09), leg(8, 'Аякс — Бенфика', 'total', 'Меньше (2.5)', 2.5, 2.2, now - 9500, [0, 0], 0.08)], 'выигрыш', 2.6 * 2.2)]
for i, (k, legs, st, mult) in enumerate(E):
    o = 1.0
    for l in legs: o *= l['odds']
    cur = con.execute('INSERT INTO expr (created, size, bookmaker, legs, odds, ev_prod, status, mult, kind) VALUES (?,?,?,?,?,?,?,?,?)',
                      (now - 12000 + i * 3000, len(legs), 'Олимп', json.dumps(legs, ensure_ascii=False), o, 0.2, st, mult, k))
    for l in legs:
        con.execute('INSERT INTO leg_check (kind, ref, match_id, fam, outcome, line, odds0, t0, o60, o90, o120) VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                    (k, cur.lastrowid, l['mid'], l['fam'], l['outcome'], l['line'], l['odds'], now - 12000, l['odds'], l['odds'] if i != 0 or l['mid'] != 2 else 3.3, l['odds']))
con.commit()
ps = S.paper_stats(con, 100)
st = S.STATE.snapshot(); st['paper'] = ps
print('views', {k: v['simple_total']['n'] for k, v in ps['views'].items()}, {k: v['n'] for k, v in ps['expr_views'].items()})
from playwright.sync_api import sync_playwright
page_html = S.PAGE.replace('__VERSION__', S.VERSION)
with sync_playwright() as p:
    br = p.chromium.launch(executable_path='/opt/pw-browsers/chromium')
    for w in (1280, 390):
        for view in ('П', 'ЭА', 'ЭБ', 'У'):
            pg = br.new_page(viewport={'width': w, 'height': 900})
            pg.add_init_script(f"try{{localStorage.setItem('pview3','{view}')}}catch(e){{}}")
            pg.route('**/api/**', lambda rt: rt.fulfill(status=200, content_type='application/json', body='{}'))
            pg.route('**/api/state*', lambda rt: rt.fulfill(status=200, content_type='application/json', body=json.dumps(st, ensure_ascii=False)))
            pg.route('http://x/', lambda rt: rt.fulfill(status=200, content_type='text/html; charset=utf-8', body=page_html))
            errs = []
            pg.on('pageerror', lambda e: errs.append(str(e)))
            pg.goto('http://x/'); pg.wait_for_timeout(1800)
            el = pg.query_selector('#paper')
            el.screenshot(path=f'/tmp/claude-0/shot/p134_{view}_{w}.png')
            if view == 'П':
                pg.click('[data-pop="*|*|проигрыш"]'); pg.wait_for_timeout(400)
                print('окно ставок П:', pg.inner_text('#pop .mhd')[:60], '| строк', pg.evaluate("document.querySelectorAll('#pop tr').length"))
                pg.click('.mx'); pg.wait_for_timeout(300)
            if view == 'ЭА':
                pg.click('[data-epop="all"]'); pg.wait_for_timeout(400)
                pg.screenshot(path=f'/tmp/claude-0/shot/p134_pop_all_{w}.png')
                print('окно:', pg.inner_text('#pop .mhd')[:80])
                pg.wait_for_timeout(3500)      # самообновление окна — окно с купонами не закрывается
                print('после обновления открыто:', pg.evaluate("document.getElementById('pop').style.display"))
                pg.click('.mx'); pg.wait_for_timeout(300)
                pg.click('[data-epop="проигрыш"]'); pg.wait_for_timeout(400)
                print('окно:', pg.inner_text('#pop .mhd')[:80], '| купонов в окне:', pg.evaluate("document.querySelectorAll('#pop .cpn').length"))
            print(w, view, 'errors', errs[:2], pg.evaluate("(()=>{const t=document.querySelector('.ptab');return t?Math.round(t.getBoundingClientRect().right):0})()"))
            pg.close()
    br.close()
