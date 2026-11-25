"""-83: вердикт разведки контор по настоящим ответам 22.11 (BetBoom, Лига Ставок — Qrator) и по открывшемуся сайту."""
exec(open('/home/claude/bet/test_watch78.py', encoding='utf-8').read().replace("print('ВСЁ ОК')", ''))
import json
rep = json.load(open('/home/claude/bet/r1000/report.json'))
for x in rep['new_bk_recon']['sites']:
    v = S.bk_verdict(x); print(x['bk'], '→', v); assert 'не пускает' in v
r1 = S.new_bk_recon(B(), wait_ms=0, sites=[('Тест', 'https://x.ru/')])['sites'][0]
print('открытый:', r1['verdict']); assert r1['verdict'].startswith('открылся: ответов с данными')
print('ВСЁ ОК')
