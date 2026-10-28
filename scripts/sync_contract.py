"""Build the v2 universal contract from the server's field registry."""
import json,sys,subprocess
from pathlib import Path
import yaml
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from backend.domain import LABELS
from backend.version import API_VERSION
path=ROOT/'contracts/card.schema.json';card=json.loads(path.read_text(encoding='utf-8'))
card['title']='ProductCard v2';card['description']='Универсальный черновик; обязательно только название товара. Остальные характеристики необязательны.'
card['properties']['schema_version']={'const':'2.2'}
card['properties']['fields'].update(minItems=1,maxItems=80)
card['properties']['photos']['minItems']=0
card['$defs']['Photo']['properties']['quality']['enum']=list(dict.fromkeys(card['$defs']['Photo']['properties']['quality']['enum']+['not_analyzed']))
defs=card['$defs'];ids={'type':'string','pattern':'^[a-z][a-z0-9_]{0,63}$'};category={'type':'string','minLength':1,'maxLength':200}
defs['Field']['properties']['field_id']=ids
defs['Field']['properties']['label']={'type':'string','minLength':1,'maxLength':100}
defs['Source']['properties']['kind']['enum']=['ocr_text','user_input','classifier']
for key in ('selected','suggested'): defs['Category']['properties'][key]=category
# Retained only for reading historical observations, no synthetic classifier runs in v2.
defs['CategoryScore']['properties']['label']={'type':'string','minLength':1}
defs['Readiness']['properties']['required_total']={'const':1}
defs['Readiness']['properties']['required_filled']={'type':'integer','minimum':0,'maximum':1}
path.write_text(json.dumps(card,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
path=ROOT/'contracts/openapi.yaml';doc=yaml.safe_load(path.read_text(encoding='utf-8'));schemas=doc['components']['schemas']
def refs(v): return json.loads(json.dumps(v).replace('#/$defs/','#/components/schemas/'))
schemas['Card']=refs({k:v for k,v in card.items() if k not in ('$schema','$defs','title','description')})
schemas.update({k:refs(v) for k,v in defs.items()})
schemas['FieldUpdate']['properties']['field_id']=ids
schemas['FieldUpdate']['properties']['required']={'type':'boolean','description':'Устаревший параметр. Игнорируется: обязательно только название товара.'}
schemas['InitialData']['properties']['fields']['properties']={key:{'type':['string','null'],'maxLength':4000} for key in LABELS}
schemas['InitialData']['properties']['category']=category
schemas['InitialData']['properties']['required_fields']={'type':'array','items':ids,'uniqueItems':True,'maxItems':len(LABELS)}
schemas['CategoryUpdate']['properties']['selected']=category
# Duplicate updates would otherwise make precedence depend on array order.
schemas['PatchCard']['properties']['field_updates']['maxItems']=80
def obj(props,required=None): return {'type':'object','additionalProperties':False,'properties':props,'required':list(props) if required is None else required}
def enum(*v): return {'type':'string','enum':list(v)}
s={'type':'string'};b={'type':'boolean'};integer={'type':'integer','minimum':1}
for name in list(schemas):
 if name.startswith('Catalog'): schemas.pop(name)
for route in list(doc['paths']):
 if route.endswith(('/catalog-lookup','/catalog-apply')): doc['paths'].pop(route)
doc['paths']['/api/v1/config']['get']['responses']['200']['content']['application/json']['schema']=obj({'labels':{'type':'object','additionalProperties':s},'required_total':{'const':1},'processing':s,'classifier':s,'ocr_modes':{'type':'array','items':{'$ref':'#/components/schemas/OCRMode'}}})

schemas['OCRMode']=obj({'id':enum('local','api'),'label':s,'provider':s,'available':b,'sends_photos':b,'notice':s})
schemas['Health']['properties']['providers']['additionalProperties']={'anyOf':[s,{'type':'array','items':{'$ref':'#/components/schemas/OCRMode'}}]}
schemas['InitialData']['properties']['ocr_mode']={**enum('local','api'),'default':'local','description':'Только api передаёт фотографии Google Cloud Vision; без ключа 503, без скрытого fallback.'}
schemas['Job']['properties']['ocr_mode']=enum('local','api')
if 'ocr_mode' not in schemas['Job']['required']:schemas['Job']['required'].append('ocr_mode')

doc['info']['version']=API_VERSION
doc['info']['title']='Полка — API'
doc['servers']=[{'url':'/','description':'Тот же адрес и порт, с которого открыт API; поддерживает HTTPS.'}]
doc['info']['description']='Прототип 2.2: универсальные товары; локальный PP-OCRv5 mobile RU/EN или Google Cloud Vision API по явному выбору. Штрихкоды и OFF/Robotoff удалены. Card schema_version=2.2, отдельное хранилище v2.2.'
path.write_text(yaml.safe_dump(doc,allow_unicode=True,sort_keys=False,width=110),encoding='utf-8')
subprocess.run([sys.executable,str(ROOT/'scripts/update_presentation_contract.py')],check=True)

subprocess.run([sys.executable,str(ROOT/'scripts/manual_contract.py')],check=True)

subprocess.run([sys.executable,str(ROOT/'scripts/upgrade_contract.py')],check=True)
