import sys, math; sys.path.insert(0,'/home/claude/stavki'); import stavki as S
lam=2.6; P=[math.exp(-lam)*lam**k/math.factorial(k) for k in range(15)]
ge=lambda n: sum(P[n:])
fair={('total',l+0.5):([ge(l+1),1-ge(l+1)],None,0) for l in range(0,8)}
w,u=S.win_push(fair,'total',3.0,0); assert abs(w-ge(4))<1e-9 and abs(u-P[3])<1e-9
w,u=S.win_push(fair,'total',3.0,1); assert abs(w-(1-ge(3)))<1e-9
ev,pw,pp=S.true_ev(fair,'total',2.75,0,2.0)   # половина на 2.5, половина на 3
assert abs(ev-(0.5*(2*ge(3)-1)+0.5*(2*ge(4)+P[3]-1)))<1e-9
# фора: разница мячей d; фора хозяев h: хозяева покрывают h+0.5 ⇔ d ≥ −h
D={-2:0.1,-1:0.2,0:0.25,1:0.25,2:0.2}
cov=lambda h: sum(p for d,p in D.items() if d+h>0)
fair={('ah',h/2):([cov(h/2),1-cov(h/2)],None,0) for h in range(-7,8,2)}
w,u=S.win_push(fair,'ah',-1.0,0); assert abs(w-0.20)<1e-9 and abs(u-0.25)<1e-9, (w,u)   # d≥2 / d=1
w,u=S.win_push(fair,'ah',-1.0,1); assert abs(w-0.55)<1e-9   # d≤0
w,u=S.win_push(fair,'ah',0.0,0); assert abs(w-0.45)<1e-9 and abs(u-0.25)<1e-9
print('возвраты: ок'); print('ВСЁ ОК')
