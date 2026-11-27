"""-145: окно «📈 Графики» — только вкладки окна (П, Р, ЭА, ЭБ, У): итог и после налога одной картинкой двумя линиями."""
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
        pg.click('.gbtn'); pg.wait_for_timeout(2500)
        titles = pg.evaluate("[...document.querySelectorAll('#pop .gcard h3')].map(x=>x.innerText)")
        print(w, titles)
        assert titles == ['Как появилась', 'Перед матчем', 'А. Экспресс из 3 ног', 'Б. Экспресс из 2 ног', 'В. Одиночные с налоговым порогом'], titles
        leg = pg.evaluate("[...document.querySelectorAll('#pop .gcard')].map(c=>c.querySelector('.gleg').innerText.replace(/\\s+/g,' '))")
        print('  ', leg)
        assert 'Итог +978 ₽' in leg[4] and 'После налога 13% +643 ₽' in leg[4]
        # подсказка: курсор на середину графика «В»
        box = pg.evaluate("(()=>{const r=document.querySelectorAll('#pop .ghit')[4].getBoundingClientRect();return [r.x+r.width/2,r.y+r.height/3]})()")
        pg.evaluate("document.querySelectorAll('#pop .gcard')[4].scrollIntoView()"); pg.wait_for_timeout(300)
        box = pg.evaluate("(()=>{const r=document.querySelectorAll('#pop .ghit')[4].getBoundingClientRect();return [r.x+r.width/2,r.y+r.height/3]})()")
        pg.mouse.move(box[0], box[1]); pg.wait_for_timeout(300)
        tip = pg.evaluate("document.querySelectorAll('#pop .gtip')[4].innerText"); print('   подсказка:', tip.replace('\n', ' | '))
        assert 'Ставка' in tip and 'после налога' in tip
        pg.screenshot(path=f'{out}/shot145_{w}.png')
        pg.evaluate("document.querySelector('#pop .mbody').scrollTop=0"); pg.wait_for_timeout(300)
        pg.screenshot(path=f'{out}/shot145_{w}_top.png')
        print('   ошибки', errs); assert not errs
        pg.close()
    br.close()
srv.shutdown()
print('ВСЁ ОК')
