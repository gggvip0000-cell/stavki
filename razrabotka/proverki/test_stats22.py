import sys, os, glob, datetime, time
if os.path.exists('/tmp/stavki.sqlite3'): os.remove('/tmp/stavki.sqlite3')
sys.path.insert(0,'/home/claude/stavki'); import stavki as S
S.HERE=__import__('pathlib').Path('/tmp'); S.MY_BOOKMAKERS=['Фонбет','PARI','Винлайн']
con=S.db_open()
text=open(glob.glob('/home/claude/bet/raw/16189400-data_4/E0.csv')[0],encoding='utf-8-sig',errors='ignore').read()
rows=S.fd_parse(text,'E0'); print('строк E0:',len(rows), rows[0])
con.executemany('INSERT OR REPLACE INTO stats VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',rows); con.commit()
r=rows[5]; div,date,home,away=r[:4]; fthg,ftag,hthg,htag,hc,ac=r[4:10]
start=datetime.datetime.fromisoformat(date+' 17:00').replace(tzinfo=S.MSK).timestamp()
S.time.time=lambda: start+5*3600
c=S.Collector(dict(S.DEFAULT_CONFIG),con)
m={'id':777,'home_en':home.lower().replace(' ','-'),'away_en':(away+' fc').lower().replace(' ','-'),'start':start}
con.execute('INSERT INTO matches (match_id,title,league,start_ts,url,home_en,away_en) VALUES (?,?,?,?,?,?,?)',(777,f'{home} — {away}','E',start,'',m['home_en'],m['away_en']))
S.STATE.matches[777]=m
print('лига в статистике:', c.stats_covered(m)); 
print('найден матч:', c.stats_result(777,start))
for fam,out,line in [('c_tt1','Больше (%g)'%(hc-0.5),hc-0.5),('h1_1x2','П1',None),('c_total','Меньше (%g)'%(hc+ac+0.5),hc+ac+0.5),('h1_ah','Ф1 (0)',0.0)]:
    con.execute("INSERT INTO paper2 (created,match_id,title,league,start_ts,strategy,event,src,bookmaker,market_name,outcome,line,odds,fair,ev,rel,fam) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (start-3600,777,'x','E',start,'А' if fam=='h1_ah' else 'Б',S.event_group(fam),'сайт','Фонбет','m',out,line,2.0,1.9,0.05,0.1,fam))
con.execute('INSERT OR REPLACE INTO results VALUES (?,?,?,?)',(777,fthg,ftag,0)); con.commit()
c.settle_paper()
res=con.execute('SELECT fam,outcome,status,profit FROM paper2').fetchall(); print(res, 'счёт тайма',hthg,htag,'угловые',hc,ac)
st={f:(s,p) for f,o,s,p in res}
assert st['c_tt1'][0]=='выигрыш' and st['c_total'][0]=='выигрыш'
exp='выигрыш' if hthg>htag else 'проигрыш'; assert st['h1_1x2'][0]==exp
print('ВСЁ ОК')
