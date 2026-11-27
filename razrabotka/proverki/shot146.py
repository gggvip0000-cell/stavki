"""-146: вкладки У/ЭБ/ЭА/Ф, у каждой значок 📈 — окно с графиком только этого способа."""
import sys, json, tempfile, pathlib, threading
sys.path.insert(0, '/home/user/stavki')
import stavki as S
S.HERE = pathlib.Path(tempfile.mkdtemp())
con = S.db_open()
r = json.load(open(sys.argv[2] if len(sys.argv) > 2 else '/home/claude/bet/r0019/report.json', encoding='utf-8'))
for t, rows in (('paper2', r['paper2']), ('expr', r['expr']['rows'])):
    cols = [c[1] for c in con.execute(f'PRAGMA table_info({t})')]
    for x in rows:
        ks = [k for k in x if k in cols]
        con.execute(f"INSERT INTO {t} ({','.join(ks)}) VALUES ({','.join('?' * len(ks))})", [x[k] for k in ks])
con.commit()
S.STATS_DB = S.db_connect(check_same_thread=False); S.STATS_STAKE = 100
srv = S.QuietServer(('127.0.0.1', 0), S.Handler); port = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()
out = sys.argv[1]
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    br = p.chromium.launch(executable_path='/opt/pw-browsers/chromium')
    for w in (1280, 390):
        pg = br.new_page(viewport={'width': w, 'height': 900})
        errs = []; pg.on('pageerror', lambda e: errs.append(str(e)))
        pg.goto(f'http://127.0.0.1:{port}/'); pg.wait_for_timeout(2500)
        tabs = pg.evaluate("[...document.querySelectorAll('.pvb')].map(x=>x.innerText.replace(/\\s+/g,' '))")
        print(w, tabs)
        names = ['Одиночные · Олимп', 'Экспресс 2 ноги · Олимп', 'Экспресс 3 ноги · Олимп', 'Одиночные · PARI и Винлайн']
        assert len(tabs) == 4 and all(t.startswith(n) and '📈' in t for t, n in zip(tabs, names)), tabs
        assert not pg.query_selector('.gbtn')
        on0 = pg.evaluate("document.querySelector('.pvb.on').innerText")
        for i, n in enumerate(names):
            pg.evaluate(f"document.querySelectorAll('.pvb .gico')[{i}].click()"); pg.wait_for_timeout(1500)
            titles = pg.evaluate("[...document.querySelectorAll('#pop .gcard h3')].map(x=>x.innerText)")
            hd = pg.evaluate("document.querySelector('#pop .mhd b').innerText")
            leg = pg.evaluate("[...document.querySelectorAll('#pop .gleg')].map(x=>x.innerText.replace(/\\s+/g,' '))")
            print('  ', n, '|', hd, '|', titles, '|', leg)
            assert hd == '📈 ' + n and len(titles) <= 1
            assert pg.evaluate("document.querySelector('.pvb.on').innerText") == on0   # вкладка не переключилась
            if i == 0:
                assert 'Итог +978 ₽' in leg[0] and 'После налога 13% +643 ₽' in leg[0]
                box = pg.evaluate("(()=>{const r=document.querySelector('#pop .ghit').getBoundingClientRect();return [r.x+r.width/2,r.y+r.height/3]})()")
                pg.mouse.move(box[0], box[1]); pg.wait_for_timeout(300)
                tip = pg.evaluate("document.querySelector('#pop .gtip').innerText"); print('   подсказка:', tip.replace('\n', ' | '))
                assert 'Ставка' in tip and 'после налога' in tip
                pg.screenshot(path=f'{out}/shot146_{w}_graf.png')
            pg.keyboard.press('Escape'); pg.wait_for_timeout(300)
        pg.evaluate("document.querySelectorAll('.pvb')[3].click()"); pg.wait_for_timeout(1500)
        pg.screenshot(path=f'{out}/shot146_{w}_F.png', full_page=False)
        pg.evaluate("document.querySelectorAll('.pvb')[0].click()"); pg.wait_for_timeout(1500)
        pg.screenshot(path=f'{out}/shot146_{w}_U.png', full_page=False)
        print('   ошибки', errs); assert not errs
        pg.close()
    br.close()
srv.shutdown()
print('ВСЁ ОК')
