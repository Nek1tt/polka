"""Generate standalone projection schemas and additive OpenAPI definitions."""
import json
from pathlib import Path
import yaml
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend.version import API_VERSION
card=json.loads((ROOT/'contracts/card.schema.json').read_text(encoding='utf-8'))
def ref(name):return {'$ref':'#/$defs/'+name}
def arr(items):return {'type':'array','items':items}
def obj(props):return {'type':'object','additionalProperties':False,'properties':props,'required':list(props)}
def enum(*values):return {'type':'string','enum':list(values)}
string={'type':'string','minLength':1}
boolean={'type':'boolean'}
integer={'type':'integer','minimum':1}
timestamp={'type':'string','format':'date-time'}
strings=arr(string)
nullable_string={'type':['string','null']}
field_id=card['$defs']['Field']['properties']['field_id']
category={'type':'string','minLength':1,'maxLength':200}
nullable=lambda name:{'anyOf':[ref(name),{'type':'null'}]}
defs={
 'TemplateBlock':obj({'block_id':string,'title':string,'kind':enum('photos','fields','description','category'),'field_ids':arr(field_id)}),
 'CardTemplate':obj({'template_id':string,'version':integer,'name':string,'supported_categories':arr(category),'blocks':arr(ref('TemplateBlock')),'description_styles':arr(enum('structured'))}),
 'ProfileField':obj({'field_id':field_id,'label':string,'required':boolean}),
 'CategoryProfile':obj({'category':category,'label':string,'supported':boolean,'fields':arr(ref('ProfileField'))}),
 'TemplateCatalog':obj({'templates':arr(ref('CardTemplate')),'category_profiles':arr(ref('CategoryProfile'))}),
 'PreviewBlock':obj({'block_id':string,'title':string,'kind':enum('photos','fields','description','category'),
                     'fields':arr(ref('Field')),'photos':arr(ref('Photo')),'description':nullable('Description'),'category':nullable('Category')}),
 'CardPreview':obj({'schema_version':{'const':'2.2'},'provider_mode':enum('live','fixture','recorded_demo'),'card_id':string,'card_revision':integer,
                    'template_id':string,'template_version':integer,'template_name':string,'is_draft':boolean,
                    'category_profile':ref('CategoryProfile'),'blocks':arr(ref('PreviewBlock')),'sources':arr(ref('Source')),
                    'readiness':ref('Readiness'),'warnings':arr(ref('Issue')),'generated_at':timestamp,'expires_at':timestamp}),
 'Recommendation':obj({'recommendation_id':string,'card_revision':integer,'rule_id':string,'priority':enum('blocker','warning'),
                        'area':enum('photos','text','category','characteristics'),
                        'action_type':enum('resolve_conflict','provide_information','enrich_optional','review_value','review_description','replace_photos','verify_photo'),
                        'reason':string,'action':string,'field_ids':strings,'photo_ids':strings,'source_ids':strings,'issue_ids':strings,
                        'question':nullable_string,'candidates':arr(ref('Candidate'))}),
 'CardRecommendations':obj({'card_id':string,'provider_mode':enum('live','fixture','recorded_demo'),'card_revision':integer,'generated_at':timestamp,'readiness':ref('Readiness'),'recommendations':arr(ref('Recommendation'))}),
 'OCRLine':obj({'text':string,'source_ids':strings,'photo_id':string,'bbox':card['$defs']['Source']['properties']['bbox'],
                'confidence':ref('Confidence'),'group':enum('useful','other','doubtful'),'reason':string,
                'field_id':{'anyOf':[field_id,{'type':'null'}]},'suggested_value':nullable_string}),
 'OCRReview':obj({'card_id':string,'card_revision':integer,'filter_version':string,
                 'counts':obj({k:{'type':'integer','minimum':0} for k in ('raw','useful','other','doubtful','duplicates')}),
                 'warnings':strings,'lines':arr(ref('OCRLine')),'notice':string}),
}
defs['PhotoAnalysis'] = obj({'job_id':string, 'requested_at':timestamp,
                             'photos':arr(ref('Photo')), 'issues':arr(ref('Issue'))})
# Additive response metadata; stored Card and its revision remain unchanged.
defs['CardRecommendations']['properties']['photo_analysis'] = nullable('PhotoAnalysis')

bundle={'$schema':'https://json-schema.org/draft/2020-12/schema','title':'Card templates, preview and recommendations',
        'oneOf':[ref(name) for name in ('TemplateCatalog','CardTemplate','CardPreview','CardRecommendations','OCRReview')],
        '$defs':{**card['$defs'],**defs}}
(ROOT/'contracts/presentation.schema.json').write_text(json.dumps(bundle,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
path=ROOT/'contracts/openapi.yaml';doc=yaml.safe_load(path.read_text(encoding='utf-8'))
doc['info']['version']=API_VERSION
doc['components']['schemas']['VersionInfo']=obj({'api_version':string,'features':obj({'templates':boolean,'preview_json':boolean,'preview_html':boolean,'recommendations':boolean,'dual_ocr':boolean,'universal_products':boolean,'copy_ocr':boolean}), 'editor_integration':obj({'template_selector':boolean,'preview_button':boolean}),'ocr_parser':string})
doc['components']['schemas'].update(json.loads(json.dumps(defs).replace('#/$defs/','#/components/schemas/')))
def param(name,schema,where='query'):
    return {'name':name,'in':where,'required':True,'schema':schema}
def operation(operation_id,description,schema,parameters=None,public=False,html=False):
    content={'text/html':{'schema':{'type':'string'}}} if html else {'application/json':{'schema':{'$ref':'#/components/schemas/'+schema}}}
    op={'operationId':operation_id,'description':description,'responses':{'200':{'description':'Успех','content':content},
        '404':{'$ref':'#/components/responses/Error'},'422':{'$ref':'#/components/responses/Error'}}}
    if parameters:op['parameters']=parameters
    if public:op['security']=[]
    else:op['responses']['409']={'$ref':'#/components/responses/Error'}
    return {'get':op}
doc['paths']['/api/v1/templates']=operation('listTemplates','Каталог версий шаблонов без товарных фактов и профили категорий из серверного домена.','TemplateCatalog',public=True)
doc['paths']['/api/v1/version']=operation('getVersionInfo','Версия реально запущенного backend и доступность функций в API и редакторе. Не содержит путей установки.','VersionInfo',public=True)
doc['paths']['/api/v1/templates/{template_id}']=operation('getTemplate','Точная версия шаблона. Неизвестный ID или версия: 404.','CardTemplate',[param('template_id',string,'path'),param('version',integer)],True)
params=[param('card_id',string,'path'),param('template_id',string),param('template_version',integer),param('expected_revision',integer)]
doc['paths']['/api/v1/cards/{card_id}/preview']=operation('previewCard','Приватная read-only проекция точной ревизии. Все шаблоны универсальны. Неизвестная версия шаблона: 404. Не подтверждает карточку. warnings содержит все текущие Issue, включая blocker.','CardPreview',params)
html_params=params+[{'name':'palette','in':'query','required':False,'schema':{'type':'string','enum':['strata','ocean','sage','clay'],'default':'strata'}}]
doc['paths']['/api/v1/cards/{card_id}/preview.html']=operation('previewCardHtml','Экранированный самостоятельный HTML той же проекции. Фото требуют ту же cookie; публичная ссылка не создаётся. No-store.','CardPreview',html_params,html=True)
doc['paths']['/api/v1/cards/{card_id}/recommendations']=operation('getCardRecommendations','Действия по сохранённым сведениям и последнему успешному OCR-анализу точного набора фото. photo_analysis содержит задачу, время запуска, фото и диагностические замечания; null, если актуального результата нет. Только чтение: факты, ревизия, подтверждение и readiness сохранённой карточки не меняются.','CardRecommendations',[param('card_id',string,'path'),param('expected_revision',integer)])
doc['paths']['/api/v1/cards/{card_id}/ocr-review']=operation('getOCRReview','Приватный отбор OCR-строк точной ревизии: useful/other/doubtful, точные повторы объединены. Исходные Source и карточка не меняются. Отбор по правилам не подтверждает факты и не восстанавливает текст.','OCRReview',[param('card_id',string,'path'),param('expected_revision',integer)])
path.write_text(yaml.safe_dump(doc,allow_unicode=True,sort_keys=False,width=110),encoding='utf-8')
print(f'Generated presentation.schema.json and OpenAPI {API_VERSION}; Card schema 2.2.')
