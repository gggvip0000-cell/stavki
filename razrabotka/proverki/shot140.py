"""-140: «+N/−N» в таблице экспрессов: купон рассчитался — видно, откуда куда; точка на вкладке; закрыл окно по цифре — сброс."""
import sys, json, tempfile, pathlib, time
sys.path.insert(0, '/home/user/stavki')
import stavki as S
S.HERE = pathlib.Path(tempfile.mkdtemp())
con = S.db_open()
now = time.time()
for i in range(4):
    legs = [{'mid': 100 + 3 * i + j, 'fam': 'total', 'outcome': 'Меньше (2.5)', 'line': 2.5, 'odds': 2.0, 'fair': 1.9, 'ev': 0.06,
             'start_ts': now - 1800, 'title': f'Команда {i}{j} — Соперник {i}{j}'} for j in range(3)]
    con.execute('INSERT INTO expr (created, size, bookmaker, legs, odds, ev_prod, status, kind) VALUES (?,?,?,?,?,?,?,?)',
                (now - 4000 + i, 3, 'Олимп', json.dumps(legs, ensure_ascii=False), 8.0, 0.19, 'open', 'ЭА'))
con.commit()
def state():
    return json.dumps(dict(S.STATE.snapshot(), paper=S.paper_stats(con, 100)), ensure_ascii=False)
ST = {'s': state()}
from playwright.sync_api import sync_playwright
page_html = S.PAGE.replace('__VERSION__', S.VERSION)
out = sys.argv[1] if len(sys.argv) > 1 else '/tmp'
def cells(pg):
    return pg.evaluate("[...document.querySelectorAll('#paper .ptab tr.tot td')].map(t=>t.innerText.replace(/\\s+/g,' ').trim())")
with sync_playwright() as p:
    br = p.chromium.launch(executable_path='/opt/pw-browsers/chromium')
    pg = br.new_page(viewport={'width': 1280, 'height': 800})
    pg.add_init_script("try{if(!localStorage.getItem('pview3'))localStorage.setItem('pview3','ЭА')}catch(e){}")
    pg.route('**/api/**', lambda rt: rt.fulfill(status=200, content_type='application/json', body='{}'))
    pg.route('**/api/state*', lambda rt: rt.fulfill(status=200, content_type='application/json', body=ST['s']))
    pg.route('http://x/', lambda rt: rt.fulfill(status=200, content_type='text/html; charset=utf-8', body=page_html))
    errs = []; pg.on('pageerror', lambda e: errs.append(str(e)))
    pg.goto('http://x/'); pg.wait_for_timeout(1500)
    c0 = cells(pg); print('сначала', c0); assert not any('+' in c or '−' in c for c in c0[1:7]), c0
    # уходим на «Как появилась», купон 1 проигрывает, купон 2 выигрывает
    pg.click('.pvb:nth-child(1)'); pg.wait_for_timeout(500)
    con.execute("UPDATE expr SET status='проигрыш', mult=0, settled=? WHERE id=1", (now,))
    con.execute("UPDATE expr SET status='выигрыш', mult=8, settled=? WHERE id=2", (now,)); con.commit()
    ST['s'] = state(); pg.wait_for_timeout(3600)
    dot = pg.evaluate("!!document.querySelector('.pvb:nth-child(3) .tdot')"); print('точка на вкладке А:', dot); assert dot
    pg.click('.pvb:nth-child(3)'); pg.wait_for_timeout(1200)
    c1 = cells(pg); print('после', c1)
    # Сделано 4 | ✓ 1 +1 | ✗ 1 +1 | ↩ | Ждут | Идут 2 −2 | +700 +700 | −100 −100 | +600 +600
    assert '+1' in c1[2] and '+1' in c1[3] and '−2' in c1[6] and '+700' in c1[7] and '−100' in c1[8], c1
    pg.screenshot(path=f'{out}/shot140_table.png', clip={'x': 0, 'y': 0, 'width': 1280, 'height': 260})
    # открыл «✗» — купон выделен; закрыл — в ✗ и Идут −1 ушли, ✓ осталось
    pg.click('[data-epop="проигрыш"]'); pg.wait_for_timeout(500)
    assert pg.evaluate("document.querySelectorAll('#pop tr.chg.exh').length") == 1
    pg.screenshot(path=f'{out}/shot140_pop.png')
    pg.click('.mx'); pg.wait_for_timeout(3600)
    c2 = cells(pg); print('после закрытия ✗', c2)
    assert '+1' not in c2[3] and '+1' in c2[2] and '−1' in c2[6], c2
    # перезагрузка окна не сбрасывает
    pg.reload(); pg.wait_for_timeout(1800); c3 = cells(pg); print('после перезагрузки', c3); assert c3 == c2, (c3, c2)
    pg.click('[data-epop="all"]'); pg.wait_for_timeout(400); pg.click('.mx'); pg.wait_for_timeout(3600)
    c4 = cells(pg); print('после «Сделано»', c4); assert not any('+' in c or '−' in c for c in c4[1:7] if c and c[0] != '+' and c[0] != '−'), c4
    print('ошибки', errs); assert not errs
    br.close()
print('ВСЁ ОК')
