exec(open('/home/claude/bet/test_pinflush84.py', encoding='utf-8').read().replace("print('ВСЁ ОК')", ''))
import io, zipfile, json
mid2 = mid
c.con.execute("INSERT OR REPLACE INTO cand (match_id, bookmaker, src, market_name, outcome, line, start_ts, first_seen, odds, fair, ev, pin_age, closing_fair, clv, done, fam) VALUES (?, 'PARI', 'сайт', '1Х2', 'П1', NULL, ?, ?, 2.5, 2.0, 0.05, 10, 2.5, 0, 1, '1x2')", (mid2, S.STATE.matches[mid2]['start'], clock[0]))
c.con.commit(); S.COLLECTOR = c
b = S.build_report(c.con)
d = json.loads(zipfile.ZipFile(io.BytesIO(b)).read('report.json')) if isinstance(b, (bytes, bytearray)) else b
j = d['pin_jumps']; print(type(j), j if isinstance(j, dict) else (len(j), j[0]['pin_match'], len(j[0]['history'])))
assert isinstance(j, list) and j and j[0]['pin_match'] and j[0]['history']
print('ВСЁ ОК')
