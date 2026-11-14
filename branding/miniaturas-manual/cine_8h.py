from PIL import Image, ImageDraw, ImageFont, ImageFilter
import numpy as np, sys
W,H=1280,720; F='/home/claude/quiet-cosmos/branding/fonts/inter/'; NIGHT=np.array([4,6,18],np.float32)
rng=np.random.default_rng(7)
c=np.ones((H,W,3),np.float32)*NIGHT
YY,XX=np.mgrid[0:H,0:W].astype(np.float32)
n2=np.asarray(Image.fromarray((rng.random((H//4,W//4))*255).astype('uint8')).resize((W,H),Image.BICUBIC).filter(ImageFilter.GaussianBlur(10)),np.float32)/255
band=np.exp(-((YY-(0.16*H-0.12*(XX-W/2)))/70)**2)
c+=(band*(0.3+1.2*(n2-0.35).clip(0))*26)[...,None]*np.array([0.82,0.86,1.0])
for _ in range(700):
    x,y=int(rng.integers(0,W)),int(rng.integers(0,int(H*0.40))); bright=rng.random()<0.07
    b=rng.uniform(160,255) if bright else rng.uniform(35,110)
    c[y,x]=np.maximum(c[y,x],[b,b,b*1.08])
earth=Image.open('/home/claude/demo/hero/thumb_1_1.jpg').convert('RGB')
S=1.55; e=earth.resize((int(1344*S),int(768*S))); ea=np.asarray(e,np.float32); lum=ea.mean(2)
top=np.array([np.argmax(lum[:,x]>45) for x in range(ea.shape[1])]).astype(float)
# horizonte: ajustar una curva suave (parábola) para que el borde sea limpio y más curvo
xs=np.arange(len(top)); p=np.polyfit(xs[40:-40],top[40:-40],2)
mid=len(top)/2; top=np.polyval(p,xs)+0.00012*(xs-mid)**2
ox=-(ea.shape[1]-W)//2-120; oy=int(H*0.30)-int(np.polyval(p,mid))
hor=np.array([top[x-ox]+oy for x in range(W)])
for x in range(W):
    sx=x-ox; t=int(top[sx]-0); y0=max(0,int(hor[x]))
    if y0>=H: continue
    src0=max(0,t+(y0-int(hor[x])))
    seg=ea[src0:src0+(H-y0),sx]; yy=np.arange(y0,y0+len(seg))
    k=np.clip(0.18+0.9*((x/W)**1.4),0,1)*np.clip(1.0-1.25*(yy-hor[x])/H,0.08,1)
    seg=seg*k[:,None]*np.array([0.78,0.86,1.0])
    edge=np.clip((yy-hor[x])/1.5,0,1)[:,None]
    c[y0:y0+len(seg),x]=c[y0:y0+len(seg),x]*(1-edge)+seg*edge
atm=np.exp(-((YY-(hor[None,:]-2))/5)**2)*(0.3+1.0*(XX/W)**2)
c+=atm[...,None]*np.array([70,130,255])*0.9
city=np.zeros((H,W),np.float32)
for _ in range(1800):
    x,y=int(rng.integers(0,int(W*0.75))),int(rng.integers(int(H*0.40),H))
    if rng.random()<0.6: city[y,x]=rng.uniform(0.3,1)
city=np.asarray(Image.fromarray((city*255).astype('uint8')).filter(ImageFilter.GaussianBlur(0.8)),np.float32)/255*3
c+=(city*(YY>hor[None,:]+8)*np.clip(1-XX/W,0,1)*120)[...,None]*np.array([1,0.75,0.4])
cx=1080; cy=hor[cx]
r=np.hypot(XX-cx,(YY-cy)*2.4)
c+=(np.exp(-r/14)*255)[...,None]*np.array([1,.96,.88])+(np.exp(-r/100)*150)[...,None]*np.array([1,.68,.32])+(np.exp(-r/420)*50)[...,None]*np.array([1,.55,.25])
c*=np.clip(1-0.55*np.exp(-((YY-0.70*H)/150)**2)*np.exp(-((XX-W/2)/520)**2),0,1)[...,None]
img=Image.fromarray(np.clip(c,0,255).astype('uint8'))
def tracked(d,text,font,y,spacing,fill):
    ws=[d.textlength(ch,font=font) for ch in text]; tot=sum(ws)+spacing*(len(text)-1); x=(W-tot)/2
    for ch,w in zip(text,ws): d.text((x,y),ch,font=font,fill=fill); x+=w+spacing
    return (W-tot)/2,(W+tot)/2
big=ImageFont.truetype(F+'Inter-ExtraLight.otf',int(sys.argv[1])); small=ImageFont.truetype(F+'Inter-Light.otf',22)
sp=int(sys.argv[2])
sh=Image.new('L',(W,H),0); sd=ImageDraw.Draw(sh); sd.rectangle((150,430,W-150,590),fill=150); sh=sh.filter(ImageFilter.GaussianBlur(45))
img=Image.composite(Image.new('RGB',(W,H),(4,6,18)),img,sh.point(lambda v:int(v*0.55))); d=ImageDraw.Draw(img)
x0,x1=tracked(d,'DUERME EN MINUTOS',big,465,sp,(242,238,228))
a0,a1=tracked(d,'ESTRATO NOCTURNO',small,425,7,(176,180,242))
d.line((a0-130,439,a0-24,439),fill=(176,180,242),width=1); d.line((a1+24,439,a1+130,439),fill=(176,180,242),width=1)
d.line((W/2-30,585,W/2+30,585),fill=(176,180,242),width=1)
img.save('miniatura_8h_cine.jpg',quality=93)
