import sys, os, json
sys.path.insert(0,'/home/claude/stavki'); import stavki as S
S.HERE=__import__('pathlib').Path('/tmp/pst'); S.HERE.mkdir(exist_ok=True)
for f in S.HERE.glob('*'): f.unlink()
calls=[]
class R:
    status=200
    def text(s): return '[]'
class Req:
    def get(s,url,headers=None,timeout=None): calls.append(headers.get('x-api-key')); return R()
class Ctx: request=Req()
class Page:
    context=Ctx(); url='x'
    def on(s,*a): pass
    def goto(s,*a,**k): raise RuntimeError('net::ERR_TIMED_OUT')
    def wait_for_timeout(s,*a): pass
class B:
    def new_page(s,**k): return Page()
f=S.PinnacleFeed(); f.start(B()); print('ключ без страницы:', calls[-1]); assert calls[-1]==S.PIN_PUBLIC_KEY
json.dump({'pinnacle_key':'SAVED'}, open(S.HERE/'config.json','w'))
f=S.PinnacleFeed(); f.start(B()); print('сохранённый ключ:', calls[-1]); assert calls[-1]=='SAVED'
print('ВСЁ ОК')
