"""Проверка -62: разведка видов спорта для отчёта."""
exec(open('/home/claude/bet/test_paper8.py', encoding='utf-8').read())
class P:
    def get(self, path):
        assert path == '/sports'
        return [{'id': 29, 'name': 'Soccer', 'matchupCount': 900}, {'id': 19, 'name': 'Hockey', 'matchupCount': 120}, {'id': 1, 'name': 'X', 'matchupCount': 0}]
c.pin = P()
clock[0] = T0
r = S.sports_recon(c)
print({k: (v if k != 'fonbet' else [(x['sport'], x['events'], len(x['top_codes']), len(x['samples'])) for x in v]) for k, v in r.items()})
assert r['pinnacle_sports'] == [{'id': 29, 'name': 'Soccer', 'matchups': 900}, {'id': 19, 'name': 'Hockey', 'matchups': 120}]
assert 'fonbet' in r and r['fonbet'] and r['fonbet'][0]['samples'][0]['factors']
import json; json.dumps(r, ensure_ascii=False)
print('ВСЁ ОК')
