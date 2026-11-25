"""Проверка версии -39: кнопка «Скачать отчёт для разработки» — zip с report.json, без ключей и токенов."""
import threading, io, zipfile, json, urllib.request
exec(open('/home/claude/bet/test_paper8.py',encoding='utf-8').read())
S.STATS_DB=con
with S.STATE.lock:
    S.STATE.status['telegram']={'text':'подключён','ok':True,'chat_id':123456,'token':'SECRET-TOKEN'}
    S.STATE.status['feeds'].setdefault('Pinnacle',{})['api_key']='SECRET-KEY'
srv=S.ThreadingHTTPServer(('127.0.0.1',8791),S.Handler); threading.Thread(target=srv.serve_forever,daemon=True).start()
r=urllib.request.urlopen('http://127.0.0.1:8791/api/report')
assert r.status==200 and 'otchet_' in r.headers['Content-Disposition'], r.headers
raw=r.read(); z=zipfile.ZipFile(io.BytesIO(raw)); rep=json.loads(z.read('report.json'))
txt=json.dumps(rep,ensure_ascii=False)
print('размер zip:',len(raw),'| разделы:',sorted(rep))
assert 'SECRET' not in txt and '123456' not in txt, 'секрет в отчёте'
assert rep['paper2'] and rep['cand'] and rep['version']==S.VERSION and 'paper_stats' in rep
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b=p.chromium.launch(executable_path='/usr/bin/google-chrome',headless=True,args=['--no-sandbox'])
    pg=b.new_page(accept_downloads=True); pg.goto('http://127.0.0.1:8791/'); pg.wait_for_timeout(1500)
    pg.click('main > details > summary')
    with pg.expect_download() as d: pg.click('a.rbtn')
    print('скачалось:', d.value.suggested_filename); assert d.value.suggested_filename.startswith('otchet_')
    pg.locator('a.rbtn').screenshot(path='/home/claude/bet/btn39.png')
    b.close()
print('ВСЁ ОК')
