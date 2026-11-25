import sys
exec(open('/home/claude/bet/test_ext25.py', encoding='utf-8').read().split("x = S.ExtStats()")[0])
x=S.ExtStats(); B=Browser()
orig=Page.evaluate
def ev403(self, js, url):
    if 'sofascore' in url: return {'s':403,'t':'{"error":{"code":403,"reason":"challenge"}}'}
    return orig(self, js, url)
Page.evaluate=ev403
u=x.stats_page(B,'fc-kobenhavn-u19','vejle-u19',ev2['startTimestamp'])
print('ответ:',repr(u),'|',x.last_http)
assert u=='' and 'не пускает' in x.last_http
asked.clear(); x.stats_page(B,'fc-kobenhavn-u19','vejle-u19',ev2['startTimestamp'])
assert not [a for a in asked if 'sofascore' in a], 'после 403 Sofascore 30 мин не спрашиваем'
u=x.stats_page(B,'manchester-city','fulham',ev0['startTimestamp']); print('FotMob:',u); assert 'fotmob.com/match/5795522' in u
print('OK')
