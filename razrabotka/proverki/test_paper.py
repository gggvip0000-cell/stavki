import sys; sys.argv=['x']
exec(open('/home/claude/bet/test_direct.py',encoding='utf-8').read().split('# sims')[0])
st=S.settle_one
assert st('1x2','П1',None,2.0,2,1)==1.0 and st('1x2','Х',None,3.0,1,1)==2.0 and st('1x2','П2',None,3.0,1,1)==-1
assert abs(st('total','Больше (2.5)',2.5,1.9,2,1)-0.9)<1e-9 and st('total','Меньше (2.5)',2.5,1.9,2,1)==-1
assert st('total','Больше (3)',3.0,1.7,2,1)==0.0 and abs(st('total','Больше (3)',3.0,1.7,3,1)-0.7)<1e-9
assert abs(st('total','Больше (2.25)',2.25,2.0,1,1)-(-0.5))<1e-9   # 2 гола: половина возврат, половина проигрыш
assert abs(st('total','Больше (2.75)',2.75,2.0,2,1)-(0.5))<1e-9    # 3 гола: 2.5 выигрыш, 3 возврат
print('settle ok')
c.cfg['paper_control_from']=0.01
c.record_paper()
print(c.con.execute('select grp,bookmaker,source,market_name,outcome,odds,ev from paper').fetchall())
# результат и закрытие
c.con.execute('INSERT OR REPLACE INTO results VALUES (?,?,?,?)',(3515898,3,1,0)); c.con.commit()
c.settle_paper()
print(c.con.execute('select bookmaker,outcome,odds,status,profit,closing_fair,clv from paper').fetchall())
S.STATS_DB=c.con; S.MY_BOOKMAKERS=['Фонбет','Винлайн','PARI']
import json; print(json.dumps(S.paper_stats(c.con,100)['main'],ensure_ascii=False))
