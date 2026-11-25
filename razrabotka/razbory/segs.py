import sys, itertools, numpy as np, pandas as pd
t = pd.read_pickle(sys.argv[1])
dims = ['market', 'side', 'odds_b', 'ev_b', 'tier', 'favs']
allc = t.clv.mean()
out = []
def stat(g):
    return len(g), g.clv.mean(), g.clv.std() / max(1, len(g)) ** .5, g.profit.mean()
for r in (1, 2):
    for combo in itertools.combinations(dims, r):
        if 'market' in combo and 'side' in combo:
            continue
        for key, g in t.groupby(list(combo), observed=True):
            key = key if isinstance(key, tuple) else (key,)
            a, b = g[g.half == 0], g[g.half == 1]
            if min(len(a), len(b)) < 60:
                continue
            na, ca, sa, ra = stat(a); nb, cb, sb, rb = stat(b)
            out.append({'правило': ' + '.join(map(str, key)), 'nA': na, 'clvA': ca, 'roiA': ra, 'nB': nb, 'clvB': cb,
                        'roiB': rb, 'zA': (ca - allc) / sa, 'zB': (cb - allc) / sb})
o = pd.DataFrame(out)
o['держится'] = (o.clvA > allc) & (o.clvB > allc) & (o.zA > 1) & (o.zB > 1)
o['хуже'] = (o.clvA < allc) & (o.clvB < allc) & (o.zA < -1) & (o.zB < -1)
pd.set_option('display.width', 250); pd.set_option('display.max_rows', 200)
fmt = lambda x: x.round({'clvA': 3, 'roiA': 3, 'clvB': 3, 'roiB': 3, 'zA': 1, 'zB': 1})
print('всего: n', len(t), 'CLV', round(allc, 4), 'доход', round(t.profit.mean(), 4))
print('\nНАЙДЕНО НА A И ДЕРЖИТСЯ НА B (лучше среднего):')
print(fmt(o[o['держится']].sort_values('clvA', ascending=False)).to_string(index=False))
print('\nСТАБИЛЬНО ХУЖЕ СРЕДНЕГО:')
print(fmt(o[o['хуже']].sort_values('clvA')).to_string(index=False))
print('\nЛУЧШИЕ НА A, НЕ ПОДТВЕРДИЛИСЬ НА B (пример ловушки):')
x = o[(o.zA > 2) & ~o['держится']].sort_values('clvA', ascending=False).head(8)
print(fmt(x).to_string(index=False))
print('\nОДНОМЕРНЫЕ:')
print(fmt(o[~o['правило'].str.contains(r'\+')]).to_string(index=False))
