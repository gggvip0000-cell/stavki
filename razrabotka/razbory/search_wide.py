"""Поиск правил отбора на прошлых матчах (football-data, 2019/20–2024/25): ищем на половине A, проверяем на половине B.
Вселенная ставок: цена Bet365 (одна обычная контора, как наши) на открытии vs честная цена Pinnacle на открытии
(маржа снята пропорционально); ставка, если перевес ≥3% и кф ≤4 (как журнал cand). Мерила: CLV против закрытия
Pinnacle (главное) и доход по итогу. Рынки: исход 1X2, тотал 2.5, азиатская фора (если линия на закрытии та же)."""
import sys, warnings, hashlib
import numpy as np, pandas as pd
sys.path.insert(0, '/home/claude/bet/code'); sys.path.insert(0, '/home/claude/stavki')
from load import load
from stavki import settle_ah
warnings.filterwarnings('ignore')
d = load('/home/claude/bet/raw').copy().reset_index(drop=True)
num = lambda c: pd.to_numeric(d[c], errors='coerce').values if c in d else np.full(len(d), np.nan)
TOP = {'E0', 'SP1', 'I1', 'D1', 'F1'}
SECOND = {'E1', 'SP2', 'I2', 'D2', 'F2', 'N1', 'P1', 'B1', 'T1', 'G1', 'SC0'}
tier = np.array(['топ-5' if x in TOP else ('сильные' if x in SECOND else 'низшие') for x in d['Div']])
# половина матча — по хешу (стабильно, не зависит от порядка)
half = np.array([int(hashlib.md5(f"{a}{b}{c}".encode()).hexdigest(), 16) % 2 for a, b, c in
                 zip(d['Date'].astype(str), d['HomeTeam'], d['AwayTeam'])])
fthg, ftag = num('FTHG'), num('FTAG')
rows = []

def fair(cols):
    inv = np.column_stack([1 / num(c) for c in cols])
    return inv / inv.sum(axis=1, keepdims=True)

def add(market, side, odds, p_open, p_close, profit, fav):
    ev = odds * p_open - 1
    ok = np.isfinite(ev) & np.isfinite(p_close) & np.isfinite(profit) & (ev >= 0.03) & (odds <= 4) & (odds > 1)
    for i in np.where(ok)[0]:
        rows.append((i, market, side, odds[i], ev[i], odds[i] * p_close[i] - 1, profit[i], fav[i]))

# 1X2
po, pc = fair(['PSH', 'PSD', 'PSA']), fair(['PSCH', 'PSCD', 'PSCA'])
res = np.where(fthg > ftag, 0, np.where(fthg == ftag, 1, 2))
for k, (side, suf) in enumerate((('П1', 'H'), ('Х', 'D'), ('П2', 'A'))):
    o = np.nanmax(np.column_stack([num(b + suf) for b in ('B365','BW','IW','WH','VC','1XB','BF')]), axis=1)
    add('исход', side, o, po[:, k], pc[:, k], np.where(res == k, o - 1, -1.0), po[:, k] >= 0.5)
# тотал 2.5
po, pc = fair(['P>2.5', 'P<2.5']), fair(['PC>2.5', 'PC<2.5'])
tot = fthg + ftag
for k, (side, col) in enumerate((('Б 2.5', 'Max>2.5'), ('М 2.5', 'Max<2.5'))):
    o = num(col)
    win = (tot > 2.5) if k == 0 else (tot < 2.5)
    add('тотал', side, o, po[:, k], pc[:, k], np.where(win, o - 1, -1.0), po[:, k] >= 0.5)
# азиатская фора (только если линия на закрытии та же)
po, pc = fair(['PAHH', 'PAHA']), fair(['PCAHH', 'PCAHA'])
ln, lnc = num('AHh'), num('AHCh')
same = ln == lnc
for k, (side, col) in enumerate((('Ф хозяев', 'MaxAHH'), ('Ф гостей', 'MaxAHA'))):
    o = num(col)
    prof = np.array([settle_ah((fthg[i] - ftag[i]) * (1 if k == 0 else -1), ln[i] * (1 if k == 0 else -1), o[i])
                     if np.isfinite(o[i]) and np.isfinite(ln[i]) and np.isfinite(fthg[i]) else np.nan for i in range(len(d))])
    add('фора', side, np.where(same, o, np.nan), po[:, k], pc[:, k], prof, po[:, k] >= 0.5)

t = pd.DataFrame(rows, columns=['i', 'market', 'side', 'odds', 'ev', 'clv', 'profit', 'fav'])
t['half'] = half[t.i]; t['tier'] = tier[t.i]; t['season'] = d['Season'].values[t.i]
t['odds_b'] = pd.cut(t.odds, [1, 1.6, 2.2, 3, 4.01], labels=['кф ≤1.6', 'кф 1.6–2.2', 'кф 2.2–3', 'кф 3–4'])
t['ev_b'] = pd.cut(t.ev, [0.03, 0.05, 0.08, 1], labels=['перевес 3–5%', 'перевес 5–8%', 'перевес 8%+'], right=False)
t['favs'] = np.where(t.fav, 'фаворит', 'не фаворит')
t.to_pickle('universe_wide.pkl')
print('всего ставок', len(t), 'матчей', t.i.nunique())
print(t.groupby('half').agg(n=('clv', 'size'), clv=('clv', 'mean'), roi=('profit', 'mean')).round(4))
