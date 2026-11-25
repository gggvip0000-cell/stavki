"""-127: разведка виджета статистики PARI в настоящем браузере: ответы всех запросов, нажатие «Статистика», текст после."""
import threading, http.server, socketserver, json, os
exec(open('/home/claude/bet/test_paper8.py', encoding='utf-8').read())
from playwright.sync_api import sync_playwright
PAGE = '''<html><body><div>Wolves 1 0 Derby</div><span id=t onclick="fetch('/ssis/api/v1/stat?eventId=7').then(r=>r.json()).then(j=>{document.getElementById('w').innerText='Угловые '+j.c[0]+' : '+j.c[1]})">Статистика</span><div id=w></div>
<script>fetch('/ssis/api/v1/eventPreview?eventId=7')</script></body></html>'''.encode()
class H(http.server.BaseHTTPRequestHandler):
    def do_GET(s):
        if s.path.startswith('/ssis/api/v1/stat'):
            b, ct = json.dumps({'c': [4, 7]}).encode(), 'application/json'
        elif s.path.startswith('/ssis/api/v1/eventPreview'):
            b, ct = b'{"eventId":7,"providers":[{"id":"x1","type":"live"}]}', 'application/json'
        else:
            b, ct = PAGE, 'text/html; charset=utf-8'
        s.send_response(200); s.send_header('content-type', ct); s.end_headers(); s.wfile.write(b)
    def log_message(s, *a): pass
srv = socketserver.TCPServer(('127.0.0.1', 0), H); port = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()
url = f'http://127.0.0.1:{port}/sports/football/country/england/12018/70141363'
con.execute("INSERT INTO paper2 (created, match_id, title, start_ts, strategy, event, src, bookmaker, outcome, line, odds, ev, fam, bk_url)"
            " VALUES (0, 777, 'Вулверхэмптон — Дерби', ?, 'С', 'c_tt2', 'сайт', 'PARI', 'Меньше (3.5)', 3.5, 1.9, 0.06, 'c_tt2', ?)",
            (S.time.time() - 50 * 60, url))
# второй матч — ставка на голы и угловые в потоке есть: должен выбраться первый
con.execute("INSERT INTO paper2 (created, match_id, title, start_ts, strategy, event, src, bookmaker, outcome, line, odds, ev, fam, bk_url)"
            " VALUES (0, 778, 'Другой', ?, 'С', 'c_tt1', 'сайт', 'PARI', 'Меньше (3.5)', 3.5, 1.9, 0.06, 'c_tt1', 'http://127.0.0.1:1/x')",
            (S.time.time() - 40 * 60,))
con.execute("INSERT INTO bk_scores (match_id, part, s1, s2, comment, ts) VALUES (778, 'c', 1, 1, NULL, ?)", (S.time.time(),))
con.commit()
with sync_playwright() as p:
    br = p.chromium.launch()
    r = S.bk_stats_recon(br, con, wait_ms=1500)
    br.close()
srv.shutdown()
print({k: r[k] for k in ('match', 'corner_bet', 'corners_in_stream', 'clicked', 'corner_text', 'blocked')})
print([b['url'][-40:] for b in r['bodies']])
assert r['match'] == 'Вулверхэмптон — Дерби' and r['corner_bet'] and not r['corners_in_stream']
assert any('eventPreview' in b['url'] and 'providers' in b['body'] for b in r['bodies'])
assert any('/ssis/api/v1/stat' in b['url'] for b in r['bodies'])
assert r['clicked'] and 'Угловые 4 : 7' in r['page_text_after'] and r['corner_text']
print('ВСЁ ОК')
