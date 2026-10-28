"""2.4 additive attribute builder and explicit text assistance operations."""
import json
import sys
from pathlib import Path
import yaml
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend.llm import OUTPUT_SCHEMA
path=ROOT/'contracts/openapi.yaml'
doc=yaml.safe_load(path.read_text(encoding='utf-8'))
s=doc['components']['schemas']
def obj(props, required=None): return dict(type='object',additionalProperties=False,properties=props,required=list(props) if required is None else required)
def ref(name): return {'$ref':'#/components/schemas/'+name}
string=dict(type='string',minLength=1)
revision=dict(type='integer',minimum=1)
field_id=s['Field']['properties']['field_id']
definition=obj(dict(field_id=field_id,label=dict(type='string',minLength=1,maxLength=100),required=dict(type='boolean')),[])
definition['anyOf']=[dict(required=['field_id']),dict(required=['label'])]
s['PatchCard']['properties']['add_fields']=dict(type='array',items=definition,maxItems=79)
s['PatchCard']['properties']['remove_fields']=dict(type='array',items=field_id,maxItems=79,uniqueItems=True)
for feature in ('attribute_builder','llm_assistance','reliable_editor'):
    f=s['VersionInfo']['properties']['features'];f['properties'][feature]=dict(type='boolean')
    if feature not in f['required']:f['required'].append(feature)
s['LLMConfig']=obj(dict(available=dict(type='boolean'),provider=string,model=string,notice=string))
config=doc['paths']['/api/v1/config']['get']['responses']['200']['content']['application/json']['schema']
config['properties'].update(attribute_catalog=dict(type='array',items=obj(dict(field_id=field_id,label=string))),llm=ref('LLMConfig'))
for name in ('attribute_catalog','llm'):
    if name not in config['required']:config['required'].append(name)
s['TextAssistanceRequest']=obj(dict(expected_revision=revision,allow_external_processing=dict(type='boolean')))
s['ApplyTextAssistance']=obj(dict(expected_revision=revision,analysis_id=string))
s['TextAssistanceResult']=OUTPUT_SCHEMA
s['TextAssistance']=obj(dict(analysis_id=string,card_id=string,card_revision=revision,provider=string,model=string,prompt_version=string,
    expires_at=dict(type='string',format='date-time'),result=ref('TextAssistanceResult')))
for suffix,request,response in [('text-assistance','TextAssistanceRequest','TextAssistance'),('apply-text-assistance','ApplyTextAssistance','Card')]:
    doc['paths']['/api/v1/cards/{card_id}/'+suffix]={'post':dict(operationId=suffix.replace('-','_'),
        parameters=[dict(name='card_id',**{'in':'path'},required=True,schema=string)],
        requestBody=dict(required=True,content={'application/json':dict(schema=ref(request))}),
        responses={'200':dict(description='Успех',content={'application/json':dict(schema=ref(response))}),
            **{str(code):{'$ref':'#/components/responses/Error'} for code in (404,409,422,429,503)}})}
doc['info']['description']='Полка 2.4: конструктор характеристик, OCR по запросу, явная внешняя LLM-помощь с отдельным применением. Сессия и Origin обязательны для изменений. Бесплатность API ограничена квотами провайдера. Card 2.2 расширен необязательным label и переменным набором fields.'
s['FieldUpdate']['properties']['required'].update(deprecated=True,description='Игнорируется с 2.4.1. Обязательно только название.')
for name in ('InitialData','ManualCardCreate'):
    if 'required_fields' in s[name]['properties']:
        s[name]['properties']['required_fields'].update(deprecated=True,description='Старый список принимается для совместимости; перечисленные характеристики необязательны.')
definition['properties']['required'].update(deprecated=True,description='Игнорируется: созданная характеристика необязательна.')
doc['info']['description']='Полка 2.4.2. Обязательно только название; остальные характеристики необязательны. Проверка галочкой сохраняет значение, OCR переносится отдельным действием. Устаревшие required/required_fields игнорируются. LLM опциональна, сохранение и финальное подтверждение раздельны.'
path.write_text(yaml.safe_dump(doc,allow_unicode=True,sort_keys=False,width=110),encoding='utf-8')
(ROOT/'contracts/text-assistance.schema.json').write_text(json.dumps(OUTPUT_SCHEMA,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
