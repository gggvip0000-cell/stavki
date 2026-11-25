exec(open('/home/claude/bet/test_bkstats76.py', encoding='utf-8').read().replace("print('ВСЁ ОК')", ''))
con.execute("UPDATE paper2 SET bk_url='https://fon.bet/sports/football/country/japan/61983/70006387' WHERE match_id=555"); con.commit()
PG.inner_text = lambda s, sel: 'Требуется дополнительная проверка. Мы хотим убедиться, что имеем дело именно с вами, а не с роботом. Пожалуйста, пройдите капчу'
r = S.bk_stats_recon(B(), con)
print(r['url'], r['blocked']); assert r['url'].startswith('https://pari.ru/sports/') and r['blocked']
print('ВСЁ ОК')
