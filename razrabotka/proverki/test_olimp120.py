import sys, time, json
sys.path.insert(0, '/home/claude/stavki')
import stavki as S
f = S.OlimpFeed()
now = time.time()
far = now + 22 * 3600
f.ev = {'1': {'id': 1, 'competitionId': 77, 'startDateTime': far}, '2': {'id': 2, 'competitionId': 88, 'startDateTime': now + 1800}}
f.cev = {'9': {'id': 9, 'parentId': 1, 'competitionId': 99, 'startDateTime': far, 'name': 'УГЛ A - УГЛ B'}}
f.kid = {'1': '9'}
f.last_full = now
f.comp_ts = {'77': now - 300, '88': now - 300, '99': now - 300}
asked = []
f.get = lambda path: (asked.append(path), '{}')[1]
S.olimp_events = lambda j: []
f.poll()
assert not any('77' in a for a in asked), asked        # far match, not hot — not refreshed
assert any('88' in a for a in asked)
asked.clear(); f.comp_ts = {'77': now - 300, '88': now - 300, '99': now - 300}
f.hurry('1'); f.hurry('1', corners=True)
f.poll()
assert any('%5D=77%3A' in a for a in asked), asked
assert any('%5D=99%3A' in a for a in asked), asked
assert any('vids%5B%5D=9%3A&main=false' in a for a in asked), asked
f.hurry('nope')
print('ok')
