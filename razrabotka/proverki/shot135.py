import sys, json, tempfile, pathlib
sys.path.insert(0, '/home/user/stavki')
import stavki as S
S.HERE = pathlib.Path(tempfile.mkdtemp())
con = S.db_open()
r = json.load(open('/home/claude/bet/r0058/report.json', encoding='utf-8'))
st = S.STATE.snapshot()
st['values'] = r['values_now']
for v in st['values']:
    v['fits'] = S.view_fits(v, r['made_ts'])
st['mine'] = ['Олимп', 'PARI', 'Винлайн']
st['paper'] = S.paper_stats(con, 100)
exp = {}
for code in ('П', 'Р', 'ЭА', 'ЭБ', 'У'):
    rows = [v for v in st['values'] if v['ev'] >= 0.05 and v['odds'] <= 4 and v['bookmaker'] in st['mine'] and code in v['fits']]
    exp[code] = len(rows)
print('ожидаю по вкладкам:', exp)
from playwright.sync_api import sync_playwright
page_html = S.PAGE.replace('__VERSION__', S.VERSION)
with sync_playwright() as p:
    br = p.chromium.launch(executable_path='/opt/pw-browsers/chromium')
    pg = br.new_page(viewport={'width': 1280, 'height': 900})
    pg.add_init_script("try{localStorage.setItem('pview3','П')}catch(e){}")
    pg.route('**/api/**', lambda rt: rt.fulfill(status=200, content_type='application/json', body='{}'))
    pg.route('**/api/state*', lambda rt: rt.fulfill(status=200, content_type='application/json', body=json.dumps(st, ensure_ascii=False)))
    pg.route('http://x/', lambda rt: rt.fulfill(status=200, content_type='text/html; charset=utf-8', body=page_html))
    errs = []; pg.on('pageerror', lambda e: errs.append(str(e)))
    pg.goto('http://x/'); pg.wait_for_timeout(1500)
    got = {}
    for i, code in enumerate(('П', 'Р', 'ЭА', 'ЭБ', 'У')):
        pg.click(f'.pvb:nth-child({i + 1})'); pg.wait_for_timeout(1200)
        got[code] = pg.evaluate("[...document.querySelectorAll('.sec .bkn')].reduce((a,b)=>a+(+b.textContent),0)")
        if code == 'П':
            pg.query_selector('#cols').screenshot(path='/tmp/claude-0/shot/p135_cols_П.png')
    print('в окне:', got, 'ошибки', errs[:2])
    assert got == exp, (got, exp)
    br.close()
print('ВСЁ ОК')
