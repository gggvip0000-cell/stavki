"""-123: видимый способ П (угловые + аутсайдеры) и Р (то же за 5–15 мин до начала); две таблицы в paper_stats."""
exec(open('/home/claude/bet/test_live24.py', encoding='utf-8').read().split("# через 2 дня без данных")[0])
now = S.time.time()
def v(mid, fam, out, odds, ev, chance, left):
    return {'match_id': mid, 'market': fam, 'outcome': out, 'line': 2.5, 'src': 'сайт', 'odds': odds, 'ev': ev,
            'chance': chance, 'rel': ev / chance, 'start_ts': now + left, 'bookmaker': 'PARI'}
rows = [v(1, 'total', 'Меньше (2.5)', 1.6, 0.06, 0.66, 3600),      # МАТЧ фаворит — не П
        v(2, 'total', 'Больше (2.5)', 2.6, 0.07, 0.41, 3600),      # МАТЧ аутсайдер — П
        v(3, 'c_tt1', 'Меньше (4.5)', 1.7, 0.06, 0.62, 600),       # угловые фаворит — П и Р
        v(4, 'h1_1x2', 'П1', 2.9, 0.08, 0.37, 600)]                # 1-й тайм аутсайдер за 10 мин — П и Р
pk = {}
for c, x in S.pick_for_strategies(rows): pk.setdefault(c, set()).add(x['match_id'])
print(pk)
assert pk['П'] == {2, 3, 4} and pk['Р'] == {3, 4} and pk['Б'] == {1, 2, 3, 4}
assert pk['С'] == {3, 4} and pk['Т'] == {3, 4}          # -125: без МАТЧА
assert S.MAIN_CODE == 'С' and [c for c, _ in S.VIEW_CODES] == ['С', 'Т']
ps = S.paper_stats(con, 100)
assert set(ps['views']) == {'С', 'Т'} and ps['bets'] == ps['views']['С']['bets']
print('ВСЁ ОК')
