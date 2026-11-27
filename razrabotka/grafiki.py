"""Графики по отчёту владельца (владелец 28.11: «для каждого отчёта свой график… по оси X ставки — 1, 2, 3…, у какого метода
сколько; по Y — 2 значения, каждое отдельно: „Итог“ и „после налога 13%“ — как они менялись после каждой ставки; номера по
X — цветом: выигрыш зелёный, проигрыш красный, возврат нейтральный»).
Запуск: python3 razrabotka/grafiki.py <report.json> <папка для картинок>
Ставки — в порядке расчёта (paper2.settled / expr.settled), по 100 ₽, как в таблице окна: Итог = сумма ₽ рассчитанных ставок,
после налога — 13% с каждого выигрыша (проигрыши не вычитаются). Методы — вкладки окна: П, Р, ЭА, ЭБ, У (цены с сайта).
Рисуется SVG (без сторонних пакетов), PNG — снимком встроенного браузера (Playwright)."""
import json, sys, pathlib, math

STAKE, TAX = 100, 0.13
VIEWS = [('П', 'Как появилась'), ('Р', 'Перед матчем'), ('ЭА', 'А. Экспресс из 3 ног'), ('ЭБ', 'Б. Экспресс из 2 ног'),
         ('У', 'В. Одиночные с налоговым порогом')]
# тёмная тема, как окно программы (палитра dataviz: поверхность, чернила, линия — синий слот 1, статусы good/critical)
BG, INK, INK2, GRID, AXIS = '#191919', '#efefef', '#9c9c9c', '#303030', '#474747'
LINE, WIN, LOSS, PUSH = '#338ced', '#0aac23', '#eb6263', '#9c9c9c'


def series(r, code):
    """[(результат, ₽, подпись)] в порядке расчёта"""
    out = []
    if code in ('ЭА', 'ЭБ'):
        rows = [x for x in r['expr']['rows'] if x.get('kind') == code and x.get('status') in ('выигрыш', 'проигрыш', 'возврат')
                and x.get('mult') is not None]
        rows.sort(key=lambda x: (x.get('settled') or 0, x['id']))
        for x in rows:
            out.append((x['status'], round((x['mult'] - 1) * STAKE), f"экспресс кф {x.get('odds')}"))
    else:
        rows = [x for x in r['paper2'] if x['strategy'] == code and x['src'] == 'сайт'
                and x['status'] in ('выигрыш', 'проигрыш', 'возврат')]
        rows.sort(key=lambda x: (x.get('settled') or 0, x['id']))
        for x in rows:
            out.append((x['status'], round((x['profit'] or 0) * STAKE), f"{x.get('title')} · {x.get('outcome')}"))
    return out


def nice_ticks(lo, hi, k=6):
    span = max(hi - lo, 1)
    raw = span / k
    mag = 10 ** math.floor(math.log10(raw))
    step = min((m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw), default=10 * mag)
    a = math.floor(lo / step) * step
    b = math.ceil(hi / step) * step
    return [a + i * step for i in range(int(round((b - a) / step)) + 1)]


def esc(t):
    return str(t).replace('&', '&amp;').replace('<', '&lt;')


def fmt(v):
    return f'{v:+,.0f}'.replace(',', ' ').replace('-', '−') + ' ₽'


def panel(ys, cols, title, W, H, x0, y_top, n, every):
    """одна панель: линия накопленного ₽ после каждой ставки"""
    pl, pr, ph = 70, 90, H
    lo, hi = min(ys + [0]), max(ys + [0])
    ticks = nice_ticks(lo, hi)
    lo, hi = ticks[0], ticks[-1]
    pw = W - pl - pr
    X = lambda i: x0 + pl + pw * i / max(n, 1)
    Y = lambda v: y_top + 28 + (ph - 28) * (1 - (v - lo) / (hi - lo or 1))
    s = [f'<text x="{x0 + 8}" y="{y_top + 16}" fill="{INK2}" font-size="14">{esc(title)}</text>']
    for t in ticks:
        s.append(f'<line x1="{x0 + pl}" x2="{x0 + pl + pw}" y1="{Y(t):.1f}" y2="{Y(t):.1f}" stroke="{AXIS if t == 0 else GRID}" '
                 f'stroke-width="{1.2 if t == 0 else 0.8}"/>')
        s.append(f'<text x="{x0 + pl - 8}" y="{Y(t) + 4:.1f}" fill="{INK2}" font-size="12" text-anchor="end">'
                 f'{fmt(t).replace(" ₽", "")}</text>')
    pts = ' '.join(f'{X(i):.1f},{Y(v):.1f}' for i, v in enumerate(ys))
    s.append(f'<polyline points="{pts}" fill="none" stroke="{LINE}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>')
    if n <= 120:                                        # точка каждой ставки цветом её итога
        for i in range(1, n + 1):
            s.append(f'<circle cx="{X(i):.1f}" cy="{Y(ys[i]):.1f}" r="3.2" fill="{cols[i - 1]}" stroke="{BG}" stroke-width="1"/>')
    s.append(f'<circle cx="{X(n):.1f}" cy="{Y(ys[-1]):.1f}" r="5" fill="{LINE}" stroke="{BG}" stroke-width="2"/>')
    s.append(f'<text x="{X(n) + 10:.1f}" y="{Y(ys[-1]) + 5:.1f}" fill="{INK}" font-size="15" font-weight="700">{fmt(ys[-1])}</text>')
    # ось X: номер каждой ставки цветом её итога
    base = y_top + ph + 4
    for i in range(1, n + 1):
        if every and (i % every and i != 1):
            # метка-чёрточка у каждой ставки, номер — через шаг
            s.append(f'<rect x="{X(i) - max(1.2, pw / n * 0.4):.1f}" y="{base}" width="{max(2.4, pw / n * 0.8):.1f}" height="7" '
                     f'fill="{cols[i - 1]}"/>')
            continue
        s.append(f'<rect x="{X(i) - max(1.2, pw / n * 0.4):.1f}" y="{base}" width="{max(2.4, pw / n * 0.8):.1f}" height="7" '
                 f'fill="{cols[i - 1]}"/>')
        s.append(f'<text x="{X(i):.1f}" y="{base + 21}" fill="{cols[i - 1]}" font-size="12" font-weight="700" '
                 f'text-anchor="middle">{i}</text>')
    return '\n'.join(s)


def chart_svg(name, ser, made):
    n = len(ser)
    cols = [WIN if st == 'выигрыш' else (LOSS if st == 'проигрыш' else PUSH) for st, _, _ in ser]
    cum, cum_t, a, b = [0], [0], 0, 0
    for st, rub, _ in ser:
        a += rub
        b += rub * (1 - TAX) if rub > 0 else rub
        cum.append(a)
        cum_t.append(round(b))
    W = max(1100, min(2600, 160 + n * 22)) if n <= 60 else max(1300, min(2600, 300 + n * 3.2))
    every = 0 if n <= 60 else (5 if n <= 150 else (10 if n <= 400 else 25))
    PH = 300
    w_, l_, p_ = (sum(1 for s, _, _ in ser if s == k) for k in ('выигрыш', 'проигрыш', 'возврат'))
    H = 90 + 2 * (PH + 50) + 30
    s = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
         f'font-family="Inter, Segoe UI, Arial, sans-serif"><rect width="100%" height="100%" fill="{BG}"/>']
    s.append(f'<text x="16" y="32" fill="{INK}" font-size="22" font-weight="700">{esc(name)} — {n} рассчитанных ставок по {STAKE} ₽</text>')
    s.append(f'<text x="16" y="58" fill="{INK2}" font-size="14">✓ выиграно <tspan fill="{WIN}" font-weight="700">{w_}</tspan>   '
             f'✗ проиграно <tspan fill="{LOSS}" font-weight="700">{l_}</tspan>   ↩ возврат <tspan fill="{INK}" font-weight="700">{p_}</tspan>'
             f'   ·   цвет номера ставки: <tspan fill="{WIN}">зелёный — выигрыш</tspan>, <tspan fill="{LOSS}">красный — проигрыш</tspan>, '
             f'серый — возврат   ·   отчёт {esc(made)}</text>')
    s.append(panel(cum, cols, 'Итог, ₽ — после каждой ставки', W, PH, 0, 80, n, every))
    s.append(panel(cum_t, cols, 'После налога 13%, ₽ — 13% с каждого выигрыша, проигрыши не вычитаются', W, PH, 0, 80 + PH + 50, n, every))
    s.append(f'<text x="{W / 2:.0f}" y="{H - 6}" fill="{INK2}" font-size="12" text-anchor="middle">ставки по порядку расчёта'
             + (f' (номер подписан у каждой {every}-й, цветная метка — у каждой ставки)' if every else '') + '</text>')
    s.append('</svg>')
    return '\n'.join(s), W, H, cum[-1], cum_t[-1]


def main(rep, out):
    r = json.load(open(rep, encoding='utf-8'))
    out = pathlib.Path(out)
    out.mkdir(parents=True, exist_ok=True)
    made = r.get('made', '')
    jobs = []
    for i, (code, name) in enumerate(VIEWS, 1):
        ser = series(r, code)
        if not ser:
            print(code, name, 'нет рассчитанных ставок')
            continue
        svg, W, H, tot, tax = chart_svg(name, ser, made)
        p = out / f'grafik_{i}_{code}.svg'
        p.write_text(svg, encoding='utf-8')
        jobs.append((p, W, H))
        print(code, name, len(ser), 'итог', tot, 'после налога', tax)
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        br = pw.chromium.launch(executable_path='/opt/pw-browsers/chromium')
        for p, W, H in jobs:
            pg = br.new_page(viewport={'width': int(W), 'height': int(H)}, device_scale_factor=2)
            pg.set_content(f'<html><body style="margin:0;background:{BG}">{p.read_text(encoding="utf-8")}</body></html>')
            pg.screenshot(path=str(p.with_suffix('.png')))
            pg.close()
        br.close()


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
