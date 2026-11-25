exec(open('/home/claude/bet/test_pin11.py', encoding='utf-8').read().split('# Pinnacle перестал отвечать')[0])
P = c.pin; T = clock[0] + 5 * 3600
P.leagues[9001] = {'name': 'Australia - A-League Women', 'last': 0}; P.leagues[9002] = {'name': 'Australia - A-League', 'last': 0}
P.regular[1] = {'home': 'Melbourne Victory (W)', 'away': 'Perth Glory (W)', 'start': T, 'league': 9001}
P.regular[2] = {'home': 'Melbourne Victory', 'away': 'Perth Glory', 'start': T + 600, 'league': 9002}
ms = {501: {'id': 501, 'start': T, 'home_en': 'melbourne-victory', 'away_en': 'perth-glory', 'league': 'Австралия: Женская W-лига'},
      502: {'id': 502, 'start': T + 600, 'home_en': 'melbourne-victory', 'away_en': 'perth-glory', 'league': 'Австралия: А-Лига'}}
r1, r2 = P.map_match(1, ms), P.map_match(2, ms)
print('женский Pinnacle →', r1, '| мужской →', r2); assert r1 == (501, False) and r2 == (502, False)
P.regular[3] = {'home': 'Melbourne Victory', 'away': 'Perth Glory', 'start': T + 7200, 'league': 9002}
ms3 = {503: {'id': 503, 'start': T + 7200, 'home_en': 'melbourne-victory', 'away_en': 'perth-glory', 'league': 'Австралия: Женская W-лига'}}
r3 = P.map_match(3, ms3); print('мужской Pinnacle к женскому odds.ru →', r3); assert r3 is None
print('ВСЁ ОК')
