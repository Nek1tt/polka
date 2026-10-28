"""Additive 2.3 operations; existing Card 2.2 observations remain readable."""
import copy
import json
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[1]
path = ROOT / 'contracts/openapi.yaml'
doc = yaml.safe_load(path.read_text(encoding='utf-8'))
schemas = doc['components']['schemas']
ref = lambda name: {'$ref': '#/components/schemas/' + name}
def obj(props, required=None):
    return dict(type='object', additionalProperties=False, properties=props, required=list(props) if required is None else required)

revision = dict(type='integer', minimum=1)
string = dict(type='string', minLength=1)
schemas['ManualCardCreate'] = obj({k: copy.deepcopy(v) for k, v in schemas['InitialData']['properties'].items() if k != 'ocr_mode'}, [])
schemas['SuggestionJobCreate'] = obj(dict(expected_revision=revision, ocr_mode=dict(type='string', enum=['local', 'api'])))
schemas['AcceptSuggestion'] = obj(dict(expected_revision=revision, job_id=string,
    field_id=schemas['Field']['properties']['field_id'], source_ids=dict(type='array', items=string, minItems=1, maxItems=100, uniqueItems=True),
    replace_existing=dict(type='boolean', default=False)), ['expected_revision', 'job_id', 'field_id', 'source_ids'])
schemas['CardSuggestions'] = obj(dict(job_id=string, analysis_card=ref('Card'), review=ref('OCRReview')))

def endpoint(method, operation, request_schema, response_schema, status='200', *, multipart=False, root=False):
    result = dict(operationId=operation, responses={status: dict(description='Успех', content={'application/json': dict(schema=ref(response_schema))})})
    for code in ('404', '409', '413', '415', '422', '429', '503'):
        result['responses'][code] = {'$ref': '#/components/responses/Error'}
    if not root:
        result['parameters'] = [dict(name='card_id', **{'in': 'path'}, required=True, schema=string)]
    else:
        result['security'] = []
    if request_schema:
        result['requestBody'] = dict(required=True, content={('multipart/form-data' if multipart else 'application/json'): dict(schema=request_schema if multipart else ref(request_schema))})
    return {method: result}

doc['paths']['/api/v1/cards'] = endpoint('post', 'createManualCard', 'ManualCardCreate', 'Card', '201', root=True)
doc['paths']['/api/v1/cards']['post']['description'] = 'Пустой ручной черновик без OCR и фотографий. Создаёт приватную сессию, модель не требуется; исходные значения непроверенные.'
schemas['CardSummary'] = obj(dict(card_id=string, revision=revision, title=string,
    created_at=dict(type='string', format='date-time'), expires_at=dict(type='string', format='date-time'),
    photo_url=dict(type=['string', 'null']), state=schemas['Readiness']['properties']['state']))
schemas['CardList'] = obj(dict(cards=dict(type='array', items=ref('CardSummary'))))
schemas['CardDeleted'] = obj(dict(deleted=dict(const=True), card_id=string))
doc['paths']['/api/v1/cards'].update(endpoint('get', 'listCards', None, 'CardList', root=True))
doc['paths']['/api/v1/cards']['get'].pop('security', None)
doc['paths']['/api/v1/cards']['get']['description'] = 'Список неистёкших товаров текущей приватной сессии. Внутренние OCR-результаты не включаются. Карточки хранятся 24 часа по умолчанию.'
doc['paths']['/api/v1/cards/{card_id}'].update(endpoint('delete', 'deleteCard', None, 'CardDeleted'))
doc['paths']['/api/v1/cards/{card_id}']['delete']['parameters'].append(dict(name='expected_revision', **{'in':'query'}, required=True, schema=revision))
doc['paths']['/api/v1/cards/{card_id}']['delete']['description'] = 'Удаление товара, его подсказок и неиспользуемых фото. Требует текущую ревизию и сессию. Активный OCR блокирует удаление (409).'
export = doc['paths']['/api/v1/cards/{card_id}/export']['get']
export['description'] = 'Только confirmed текущей сессии. format=text возвращает проверенное описание без технических источников; json сохраняет полный интеграционный контракт.'
export['parameters'] = [dict(name='format', **{'in':'query'}, schema=dict(type='string', enum=['json','text'], default='json'))]
export['responses']['200']['content']['text/plain'] = dict(schema=dict(type='string'))
upload = obj(dict(expected_revision=revision, files=dict(type='array', minItems=1, maxItems=3, items=dict(type='string', format='binary'))))
doc['paths']['/api/v1/cards/{card_id}/photos'] = endpoint('post', 'attachCardPhotos', upload, 'Card', multipart=True)
doc['paths']['/api/v1/cards/{card_id}/photos']['post']['description'] = 'Добавить фото без запуска модели; максимум три. expected_revision защищает правки. Снимает подтверждение.'
doc['paths']['/api/v1/cards/{card_id}/ocr-jobs'] = endpoint('post', 'createSuggestionJob', 'SuggestionJobCreate', 'Job', '202')
doc['paths']['/api/v1/cards/{card_id}/ocr-jobs']['post']['description'] = 'Явно запустить local/api по прикреплённым фото. Результат отдельный, рабочая карточка не меняется. Только api передаёт фото Google.'
doc['paths']['/api/v1/cards/{card_id}/ocr-suggestions'] = endpoint('get', 'getCardSuggestions', None, 'CardSuggestions')
doc['paths']['/api/v1/cards/{card_id}/ocr-suggestions']['get']['parameters'].append(dict(name='job_id', **{'in': 'query'}, required=True, schema=string))
doc['paths']['/api/v1/cards/{card_id}/accept-suggestion'] = endpoint('post', 'acceptCardSuggestion', 'AcceptSuggestion', 'Card')
doc['paths']['/api/v1/cards/{card_id}/accept-suggestion']['post']['description'] = 'Принять ровно одну существующую строку с её настоящими источниками. Значение вычисляет сервер; произвольный текст/score не принимается. Заполненное поле требует replace_existing=true; поле остаётся непроверенным. Истёкшая/чужая задача недоступна.'
for name in ['manual_drafts', 'opt_in_suggestions', 'product_library']:
    schemas['VersionInfo']['properties']['features']['properties'][name] = dict(type='boolean')
    if name not in schemas['VersionInfo']['properties']['features']['required']:
        schemas['VersionInfo']['properties']['features']['required'].append(name)
doc['info']['description'] = 'MVP 2.3: ручное заполнение сразу, фото отдельно, OCR только по запросу. Подсказки не перезаписывают карточку. Card 2.2 расширен пустыми photos и not_analyzed; новые данные изолированы в v2.3; прежнее хранилище не удаляется. local/API RU+EN, без штрихкодов.'
path.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False, width=110), encoding='utf-8')
