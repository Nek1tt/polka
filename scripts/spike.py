"""Synthetic smoke, NOT a real product benchmark. Includes RU and EN non-food label. Includes RU and EN non-food label."""
import sys, time, json, threading
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PIL import Image,ImageDraw,ImageFont,ImageFilter
from backend.inference import Providers,ROOT
from backend.domain import uid
import psutil

out=ROOT/'data/demo';out.mkdir(parents=True,exist_ok=True)
font_path='C:/Windows/Fonts/arial.ttf' if sys.platform=='win32' else '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
font=ImageFont.truetype(font_path,32)
cases={
 'dairy':['Название: Творог молочный','Масса нетто: 250 г','Состав: молоко, закваска','Хранение: от +2 до +6 C','Срок годности: 7 суток','Производитель: Учебный пример'],
 'jam':['Название: Джем клубничный','Масса нетто: 300 г','Состав: клубника, сахар','Хранение: от +5 до +20 C','Срок годности: 12 месяцев'],
 'missing':['Название: Варенье малиновое','Масса нетто: 250 г','Состав: малина, сахар'],
 'other':['Название: Шампунь для волос','Объем: 250 мл','Состав: вода, моющая основа'],
 'conflict':['Название: Творог молочный','Масса нетто: 250 г','Состав: молоко, закваска','Хранение: от +2 до +6 C','Срок годности: 7 суток']}
cases['cable']=['Product: USB cable','Brand: Example','Model: C-20','Material: Nylon','Color: Black','Specifications: Length 2 m']
cases['cable']=['Product: USB cable','Brand: Example','Model: C-20','Material: Nylon','Color: Black','Specifications: Length 2 m']
for key,lines in cases.items():
 im=Image.new('RGB',(1100,620),'#fffdf7');d=ImageDraw.Draw(im)
 for i,line in enumerate(lines): d.text((45,45+i*65),line,font=font,fill='#172b26')
 d.text((45,550),'СИНТЕТИЧЕСКАЯ ТЕСТОВАЯ ЭТИКЕТКА',font=ImageFont.truetype(font_path,22),fill='#666666')
 im.save(out/f'{key}.png')
 if key=='dairy': im.filter(ImageFilter.GaussianBlur(12)).save(out/'blur.png')
peak=[0];stop=threading.Event()
def sample():
 while not stop.wait(.02):
  proc=psutil.Process()
  total=proc.memory_info().rss
  for child in proc.children(recursive=True):
   try:total+=child.memory_info().rss
   except psutil.Error:pass
  peak[0]=max(peak[0],total)
thread=threading.Thread(target=sample,daemon=True);thread.start()
p=Providers();t=time.perf_counter();p.check();report={'dataset':'synthetic only; real N=0','provider_ready':p.ready,'startup_seconds':time.perf_counter()-t,'cases':[]}
for key in ['dairy','jam','missing','other','cable','blur','conflict']:
 path=out/f'{key}.png';t=time.perf_counter()
 card=p.analyze([dict(photo_id=uid(),url='',width=1100,height=620,quality='uncertain')],[path],{'fields':{'net_quantity':'200 г'}} if key=='conflict' else {},lambda _:None)
 report['cases'].append({'id':key,'seconds':time.perf_counter()-t,'category':card['category'],'fields':card['fields'],'quality':card['photos'][0]['quality'],'text':[s['text'] for s in card['sources'] if s['kind']=='ocr_text']})
report['python_rss_mib']=psutil.Process().memory_info().rss/1024**2
stop.set();thread.join();report['sampled_process_tree_peak_mib']=peak[0]/1024**2
(ROOT/'docs/spike-results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({k:v for k,v in report.items() if k!='cases'},ensure_ascii=False))
for r in report['cases']:print(r['id'],r['category']['selected'],round(r['seconds'],2),[(f['field_id'],f['value']) for f in r['fields'] if f['value']])
