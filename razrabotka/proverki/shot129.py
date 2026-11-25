import sys, json, tempfile, pathlib, sqlite3
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
con.commit()
ps = S.paper_stats(con, 100)
st = S.STATE.snapshot(); st['paper'] = ps
for k, v in (r.get('values_now') or {}).items() if isinstance(r.get('values_now'), dict) else []:
    st[k] = v
print('views', {k: v['simple_total']['n'] for k, v in ps['views'].items()})
from playwright.sync_api import sync_playwright
page_html = S.PAGE.replace('__VERSION__', S.VERSION)
with sync_playwright() as p:
    br = p.chromium.launch(executable_path='/opt/pw-browsers/chromium')
    for w in (1280, 390):
        pg = br.new_page(viewport={'width': w, 'height': 900})
        pg.route('**/api/**', lambda rt: rt.fulfill(status=200, content_type='application/json', body='{}'))
        pg.route('**/api/state*', lambda rt: rt.fulfill(status=200, content_type='application/json', body=json.dumps(st, ensure_ascii=False)))
        pg.route('http://x/', lambda rt: rt.fulfill(status=200, content_type='text/html; charset=utf-8', body=page_html))
        errs = []
        pg.on('pageerror', lambda e: errs.append(str(e)))
        pg.goto('http://x/'); pg.wait_for_timeout(2500)
        print(w, 'errors', errs[:3], 'paper:', pg.inner_text('#paper')[:400].replace('\n', ' | '), '| st:', pg.inner_text('#st')[:200])
        pg.screenshot(path=f'/tmp/claude-0/shot/full_{w}.png')
        print(pg.evaluate("(()=>{const t=document.querySelector('.ptab');const p=t.parentElement;return {zoom:t.style.zoom,sw:t.scrollWidth,pw:p.clientWidth,rect:t.getBoundingClientRect().right,vw:innerWidth}})()"))
        for v in ('Р',):
            pg.evaluate("setView('"+v+"')"); pg.wait_for_timeout(500)
            print(v, pg.evaluate("(()=>{const t=document.querySelector('.ptab');return {zoom:t.style.zoom,right:t.getBoundingClientRect().right}})()"))
    br.close()
