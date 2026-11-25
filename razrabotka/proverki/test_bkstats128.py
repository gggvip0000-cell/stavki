"""-128: разведка страницы по цели corner_recon_target (без записей владельца) и по старому выбору из paper2."""
import threading, http.server, socketserver, json, os, sys, tempfile, pathlib, time
sys.path.insert(0, '/home/claude/stavki')
import stavki as S
S.HERE = pathlib.Path(tempfile.mkdtemp())
con = S.db_open()
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
with sync_playwright() as p:
    br = p.chromium.launch(executable_path=os.environ.get('PWCHROME') or None)
    assert S.bk_stats_recon(br, con, wait_ms=500) is None          # в paper2 ничего — матча нет
    r = S.bk_stats_recon(br, con, wait_ms=1500, target=(url, 'Вулверхэмптон — Дерби', 777))
    br.close()
srv.shutdown()
print({k: r[k] for k in ('match', 'match_id', 'corner_bet', 'corners_in_stream', 'clicked', 'corner_text', 'blocked')})
assert r['match'] == 'Вулверхэмптон — Дерби' and r['match_id'] == 777 and r['corner_bet'] and not r['corners_in_stream']
assert r['clicked'] and 'Угловые 4 : 7' in r['page_text_after'] and r['corner_text']
print('ВСЁ ОК')
