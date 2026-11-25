import sys; sys.path.insert(0, '/home/claude/stavki'); import stavki as S
class PG:
    url = 'https://fon.bet/rules'
    def goto(s, u, **k): s.url = u
    def wait_for_timeout(s, ms): pass
    def inner_text(s, sel): return 'Общие правила ... ' * 50 + 'Угловые удары, назначенные, но не поданные, не учитываются. Ставки рассчитываются по основному времени. ' + 'текст ' * 300
    def eval_on_selector_all(s, sel, js): return [['https://fon.bet/rules.pdf', 'Правила']]
    def close(s): pass
class B:
    def new_page(s, **k): return PG()
r = S.rules_recon(B(), 'Фонбет', 'https://fon.bet/rules', wait_ms=0)
print(r['final_url'], r['len'], len(r['bits']), r['bits'][0][-200:]); assert r['bits'] and 'не поданные' in r['bits'][0]
print('ВСЁ ОК')
