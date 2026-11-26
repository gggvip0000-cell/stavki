# -137: «database is locked» — чтение окна не мешает записи цикла, второй запуск не трогает базу
import sys, tempfile, pathlib, threading, time, sqlite3, socket
sys.path.insert(0, '/home/user/stavki'); sys.path.insert(0, '/home/claude/stavki')
import stavki as S
S.HERE = pathlib.Path(tempfile.mkdtemp())
con = S.db_open()
assert con.execute('PRAGMA journal_mode').fetchone()[0] == 'wal', 'журнал не WAL'
for i in range(2000):
    con.execute('INSERT INTO pin VALUES (?,?,?,?)', (time.time(), i, 'm', 'x'))
con.commit()
rd = S.db_connect(check_same_thread=False)
# 1) окно держит чтение (незаконченный курсор), цикл пишет и сохраняет — без ожидания
cur = rd.execute('SELECT * FROM pin'); cur.fetchone()
t = time.time(); con.execute('INSERT INTO pin VALUES (1,1,"m","y")'); con.commit()
assert time.time() - t < 1, 'запись ждала чтения'
cur.fetchall()
# 2) то же, что было до -137 (журнал DELETE, ожидание 5 с): запись падает — проверка ловит старую беду
old = pathlib.Path(tempfile.mkdtemp()) / 'x.sqlite3'
a = sqlite3.connect(str(old), timeout=0.3); a.execute('CREATE TABLE t (x)'); a.executemany('INSERT INTO t VALUES (?)', [(i,) for i in range(500)]); a.commit()
b = sqlite3.connect(str(old), timeout=0.3); c2 = b.execute('SELECT * FROM t'); c2.fetchone()
a.execute('INSERT INTO t VALUES (1)')
try:
    a.commit(); raise SystemExit('старый способ не упал — проверка ничего не доказывает')
except sqlite3.OperationalError as e:
    assert 'locked' in str(e)
# 3) две записи разом из разных связей — вторая ждёт, а не падает
s2 = S.db_connect(check_same_thread=False)
con.execute('INSERT INTO pin VALUES (2,2,"m","z")')            # цикл начал запись и не сохранил
def later():
    time.sleep(1.5); con.commit()
threading.Thread(target=later).start()
t = time.time(); s2.execute('INSERT INTO pin VALUES (3,3,"m","z")'); s2.commit()
assert 1.0 < time.time() - t < 10, time.time() - t
# 4) второй запуск (порт занят) базу не открывает
sock = socket.socket(); sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]; sock.listen()
S.HERE = pathlib.Path(tempfile.mkdtemp())
S.load_config = lambda: {'port': port, 'my_bookmakers_list': [], 'paper_stake_rub': 100, 'autostart': False}
S.webbrowser.open = lambda u: None
try:
    S.main()
except Exception as e:
    print('main упал:', str(e)[:150])
assert not (S.HERE / 'stavki.sqlite3').exists(), 'второй запуск открыл базу'
print('ВСЁ ОК 4')
