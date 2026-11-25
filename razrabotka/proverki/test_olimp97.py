import sys, json, time; sys.path.insert(0, '/home/claude/stavki'); import stavki as S
d = json.load(open('/home/claude/bet/r1631/report.json'))['olimp_recon']
comp, ugl = json.loads(d['sample_comp']), json.loads(d['sample_ugl_comp'])
evs = S.olimp_events(comp) + S.olimp_events(ugl)
now = time.time()
for e in evs:                              # сдвинуть время в будущее
    e['startDateTime'] = int(now + 3600)
bristol = {'id': '86343880', 'name': 'Бристоль Сити - Рексэм', 'team1Name': 'Бристоль Сити', 'team2Name': 'Рексэм',
           'names': {'2': 'Bristol City - Wrexham'}, 'startDateTime': int(now + 3600), 'competitionId': '1',
           'outcomes': [{'marketId': 1, 'shortName': s, 'probability': p} for s, p in (('П1', '2.1'), ('Х', '3.3'), ('П2', '3.5'))]}
full = json.dumps([{'payload': {'competitionsWithEvents': [{'events': evs + [bristol]}]}}])
calls = []
class PG:
    url = 'x'
    def evaluate(s, js, u):
        calls.append(u)
        return {'s': 200, 't': full if 'sports-with' in u else json.dumps([{'payload': {'events': evs[:2]}}])}
f = S.OlimpFeed(); f.page = PG()
f.poll()
print('событий', len(f.ev), 'УГЛ', len(f.cev), 'запросов', len(calls))
assert len(f.cev) == 24 and '86343880' in f.ev
o = f.odds_of('86343880'); print(sorted(o, key=str)[:8])
assert ('1x2', None) in o and ('c_total', 9.5) in o and ('c_ah', 0.0) in o
g = f.odds_of('86242415'); assert g[('1x2', None)] == [2.7, 3.86, 2.47] and g[('ah', -1.0)] == [4.01, 1.25]
# второй опрос — чемпионаты по расписанию (2 за раз), а не вся линия
f.comp_ts = {}; f.poll(); print('после 2-го опроса запросов', len(calls), calls[-1][-40:])
assert 3 <= len(calls) <= 7 and any('competitions-with-events' in u for u in calls[1:])
# сопоставление: русские не сошлись — английские
ev = [x for x in f.football() if x['id'] == '86343880'][0]
m = {7: {'id': 7, 'start': ev['startTime'], 'home': 'Бристоль', 'away': 'Рексем XX', 'home_en': 'Bristol City', 'away_en': 'Wrexham'}}
print('сопоставлено с', f.match_to_oddsru(ev, m)); assert f.match_to_oddsru(ev, m) == 7
# журнал: Олимп не в окне, но в записи кандидатов
S.STATE.direct_values = {('direct', 'Олимп', 7, 'Тотал', 'Больше (2.5)'): {'bookmaker': 'Олимп', 'match_id': 7, 'ev': 0.06, 'updated': now, 'first_seen': now, 'market': 'total', 'line': 2.5, 'market_name': 'Тотал', 'outcome': 'Больше (2.5)', 'odds': 1.9, 'fair': 1.8, 'p_win': 0.55, 'p_push': 0, 'pin_odds': 1.85, 'pin_ts': now, 'odds_ts': now, 'source': 'сайт'}}
assert [v for v in S.STATE.snapshot()['values'] if v['bookmaker'] == 'Олимп']   # -115: Олимп — в окне
assert [v for v in S.STATE.snapshot(journal=True)['values'] if v['bookmaker'] == 'Олимп']
print('ВСЁ ОК')
