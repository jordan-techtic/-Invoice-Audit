def lum(h):
    h=h.lstrip('#'); r,g,b=[int(h[i:i+2],16)/255 for i in (0,2,4)]
    f=lambda c: c/12.92 if c<=0.03928 else ((c+0.055)/1.055)**2.4
    return 0.2126*f(r)+0.7152*f(g)+0.0722*f(b)
def cr(a,b):
    la,lb=sorted([lum(a),lum(b)],reverse=True); return (la+0.05)/(lb+0.05)
pairs=[("ink on bg","#1B2B3A","#F3F5F8"),("ink-muted on bg","#4F5F70","#F3F5F8"),("ink-muted on white","#4F5F70","#FFFFFF"),
("white on primary","#FFFFFF","#1F3A56"),("money on white","#8F5A00","#FFFFFF"),("money on bg","#8F5A00","#F3F5F8"),
("ink on amber fill","#1B2B3A","#F2A900"),("money on amber-soft","#8F5A00","#FFF4D9"),("ink on amber-soft","#1B2B3A","#FFF4D9"),
("confirmed on white","#1E7046","#FFFFFF"),("confirmed on soft","#1E7046","#E4F2EA"),("dismissed on white","#5F6B78","#FFFFFF"),
("dismissed on soft","#5F6B78","#ECEFF2"),("danger on white","#B42318","#FFFFFF"),("border vs white (ui 3:1?)","#8A98A8","#FFFFFF"),
("focus ring vs bg","#1F3A56","#F3F5F8"),("amber fill vs white (ui)","#F2A900","#FFFFFF"),("primary bar vs white","#1F3A56","#FFFFFF"),("bar-muted vs white","#9FB0C2","#FFFFFF")]
for n,a,b in pairs: print(f"{n:28s} {cr(a,b):5.2f}")
