"""Safety/atomicity tests. Provider responses are mocks, not a model quality benchmark."""
import copy
import json
import httpx
import pytest
from backend import main, llm
from test_presentation import client

def create(client):
    r=client.post('/api/v1/cards',json={'fields':{'product_name':'Футболка'}})
    assert r.status_code==201,r.text
    return r.json()

def update(client,card,**payload):
    return client.patch('/api/v1/cards/'+card['card_id'],json=dict(expected_revision=card['revision'],**payload))

def test_custom_field_lifecycle_preview_export_and_atomic_rejections(client):
    card=create(client);assert [f['field_id'] for f in card['fields']]==['product_name']
    card=update(client,card,add_fields=[{'label':'Обхват рукоятки','required':True}]).json()
    field=card['fields'][-1];key=field['field_id'];assert field['label']=='Обхват рукоятки'
    assert key not in card['readiness']['missing_fields'] and field['required'] is False
    before=copy.deepcopy(card)
    for payload in ({'remove_fields':['product_name']},{'add_fields':[{'label':'Название товара'}]}, {'field_updates':[dict(field_id='invented',value='x',reviewed=True)]}):
        assert update(client,card,**payload).status_code==422
        assert client.get('/api/v1/cards/'+card['card_id']).json()==before
    card=update(client,card,field_updates=[dict(field_id=f['field_id'],value='12 см' if f['field_id']==key else f['value'],reviewed=True) for f in card['fields']]).json()
    assert 'Обхват рукоятки: 12 см' in card['description']['text']
    for tid in ('market_v1','studio_v1','compact_v1'):
        r=client.get('/api/v1/cards/'+card['card_id']+'/preview.html',params=dict(template_id=tid,template_version=1,expected_revision=card['revision']))
        assert r.status_code==200 and 'Обхват рукоятки' in r.text and '12 см' in r.text
    card=update(client,card,description_update=dict(text=card['description']['text'],reviewed=True,asserted_as_user_input=False)).json()
    card=client.post('/api/v1/cards/'+card['card_id']+'/confirm',json={'expected_revision':card['revision']}).json()
    assert client.get('/api/v1/cards/'+card['card_id']+'/export').json()['fields'][-1]['label']=='Обхват рукоятки'
    card=update(client,card,remove_fields=[key]).json()
    assert card['confirmation'] is None and all(f['field_id']!=key for f in card['fields'])
    assert 'Обхват' not in card['description']['text']

def result():
    return dict(description_sentences=[dict(text='Футболка.',fact_ids=['product_name'])],recommendations=[],questions=[dict(question='Какой размер товара?',suggested_label='Размер')])

@pytest.mark.parametrize('change',[lambda r:r['description_sentences'][0].update(fact_ids=['unknown']),lambda r:r['description_sentences'][0].update(text='Размер 99.'),lambda r:r.update(recommendations=[dict(kind='clarity',message='Уточните',fragment='выдуманная цитата',fact_ids=[])]),lambda r:r.update(extra='x')])
def test_unverifiable_model_outputs_rejected(change):
    data=dict(facts=[dict(fact_id='product_name',value='Футболка')],current_description='')
    response=result();change(response)
    with pytest.raises(llm.LLMError):llm.validate_output(response,data)

def test_llm_disabled_consent_and_paid_fallback_are_explicit(client,monkeypatch):
    monkeypatch.setenv('LLM_PROVIDER','openrouter')
    card=create(client);url='/api/v1/cards/'+card['card_id']+'/text-assistance'
    monkeypatch.setenv('LLM_API_KEY','')
    assert client.post(url,json=dict(expected_revision=card['revision'],allow_external_processing=True)).status_code==503
    monkeypatch.setenv('LLM_API_KEY','test-only');monkeypatch.setenv('LLM_MODEL','paid-model')
    assert llm.public_config()['available'] is False
    monkeypatch.setenv('LLM_MODEL','openai/gpt-oss-120b:free')
    assert client.post(url,json=dict(expected_revision=card['revision'],allow_external_processing=False)).status_code==422

def test_llm_proposal_cache_isolation_revision_apply_and_review(client,monkeypatch):
    monkeypatch.setenv('LLM_API_KEY','test-only');monkeypatch.setenv('LLM_PROVIDER','openrouter');monkeypatch.setenv('LLM_MODEL','openai/gpt-oss-120b:free')
    monkeypatch.setenv('LLM_DAILY_BUDGET','1000')
    calls=[]
    async def fake(data):calls.append(data);return result()
    monkeypatch.setattr(llm,'generate',fake)
    card=create(client);path='/api/v1/cards/'+card['card_id']
    request=dict(expected_revision=card['revision'],allow_external_processing=True)
    assert client.post(path+'/text-assistance',json=request,headers={'Origin':'https://wrong.test'}).status_code==403
    response=client.post(path+'/text-assistance',json=request);assert response.status_code==200,response.text
    analysis=response.json();main.validate('TextAssistance',analysis)
    assert client.get(path).json()==card
    assert client.post(path+'/text-assistance',json=request).json()==analysis and len(calls)==1
    apply=dict(expected_revision=card['revision'],analysis_id=analysis['analysis_id'])
    assert client.post(path+'/apply-text-assistance',json=apply,headers={'cookie':'card_session=foreign'}).status_code==404
    r=client.post(path+'/apply-text-assistance',json=apply);assert r.status_code==200,r.text
    card=r.json();assert card['description']['mode']=='llm' and card['description']['reviewed'] is False
    assert card['description']['source_ids']==card['fields'][0]['source_ids']
    assert client.post(path+'/apply-text-assistance',json=apply).status_code==409
    card=update(client,card,description_update=dict(text=card['description']['text'],reviewed=True,asserted_as_user_input=False)).json()
    assert card['description']['reviewed'] and card['description']['mode']=='llm'

def test_http_adapter_never_sends_photos_keys_in_payload_or_tools(monkeypatch):
    import asyncio
    monkeypatch.setenv('LLM_API_KEY','test-only');monkeypatch.setenv('LLM_PROVIDER','openrouter');monkeypatch.setenv('LLM_MODEL','openai/gpt-oss-120b:free')
    real=httpx.AsyncClient;captured=[]
    def handler(request):
        payload=json.loads(request.content);captured.append(payload)
        assert request.url.host=='openrouter.ai'
        assert payload['provider']==dict(require_parameters=True,allow_fallbacks=False)
        assert 'response_format' not in payload
        assert 'tools' not in payload and 'test-only' not in request.content.decode()
        return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':json.dumps(result())}}]})
    monkeypatch.setattr(llm.httpx,'AsyncClient',lambda **kw:real(transport=httpx.MockTransport(handler),**kw))
    data=dict(facts=[dict(fact_id='product_name',value='Футболка')],current_description='')
    assert asyncio.run(llm.generate(data))==result() and len(captured)==1

def test_seller_claims_are_input_not_demands_for_proof(client):
    card=create(client)
    card=update(client,card,description_update=dict(text='Гипоаллергенная футболка',reviewed=False,asserted_as_user_input=False)).json()
    data=llm.inputs(card)
    assert any(f['value']=='Гипоаллергенная футболка' for f in data['facts'])

def test_budget_survives_deleted_product(client,monkeypatch):
    monkeypatch.setenv('LLM_API_KEY','test-only');monkeypatch.setenv('LLM_PROVIDER','openrouter');monkeypatch.setenv('LLM_MODEL','test:free')
    with main.db() as conn:
        count=conn.execute("SELECT COUNT(*) FROM objects WHERE kind='llm_attempt' AND expires>?",(main.now(),)).fetchone()[0]
    monkeypatch.setenv('LLM_DAILY_BUDGET',str(count+1))
    async def fake(data):return result()
    monkeypatch.setattr(llm,'generate',fake)
    card=create(client);path='/api/v1/cards/'+card['card_id']
    response=client.post(path+'/text-assistance',json=dict(expected_revision=1,allow_external_processing=True))
    assert response.status_code==200,response.text
    assert client.delete(path,params={'expected_revision':1}).status_code==200
    other=create(client)
    response=client.post('/api/v1/cards/'+other['card_id']+'/text-assistance',json=dict(expected_revision=1,allow_external_processing=True))
    assert response.status_code==429,response.text

def test_groq_strict_adapter_and_rate_limit(monkeypatch):
    import asyncio
    monkeypatch.setenv('LLM_API_KEY','test-only');monkeypatch.setenv('LLM_PROVIDER','groq');monkeypatch.setenv('LLM_MODEL','openai/gpt-oss-120b');monkeypatch.setenv('LLM_GROQ_FREE_PLAN','1')
    real=httpx.AsyncClient
    def handler(request):
        payload=json.loads(request.content)
        assert request.url.host=='api.groq.com'
        assert payload['response_format']['json_schema']['strict'] is True
        assert payload['response_format']['json_schema']['schema']==llm.provider_schema()
        assert 'uniqueItems' not in json.dumps(payload['response_format'])
        return httpx.Response(429)
    monkeypatch.setattr(llm.httpx,'AsyncClient',lambda **kw:real(transport=httpx.MockTransport(handler),**kw))
    with pytest.raises(llm.LLMError) as error:
        asyncio.run(llm.generate(dict(facts=[],current_description='')))
    assert error.value.code=='LLM_RATE_LIMIT'

def test_provider_schema_does_not_weaken_local_validation():
    assert 'uniqueItems' not in json.dumps(llm.provider_schema())
    assert llm.OUTPUT_SCHEMA['properties']['description_sentences']['items']['properties']['fact_ids']['uniqueItems'] is True
    duplicate=result();duplicate['description_sentences'][0]['fact_ids']=['product_name','product_name']
    with pytest.raises(llm.LLMError):llm.validate_output(duplicate,dict(facts=[dict(fact_id='product_name',value='Футболка')],current_description=''))

def test_schema_rejection_has_safe_diagnostic(client,monkeypatch,caplog):
    monkeypatch.setenv('LLM_API_KEY','test-only');monkeypatch.setenv('LLM_PROVIDER','groq');monkeypatch.setenv('LLM_MODEL','openai/gpt-oss-120b');monkeypatch.setenv('LLM_GROQ_FREE_PLAN','1');monkeypatch.setenv('LLM_DAILY_BUDGET','1000')
    real=httpx.AsyncClient
    def handler(request):return httpx.Response(400,json={'error':{'message':'uniqueItems schema unsupported secret-text'}})
    monkeypatch.setattr(llm.httpx,'AsyncClient',lambda **kw:real(transport=httpx.MockTransport(handler),**kw))
    card=create(client)
    response=client.post('/api/v1/cards/'+card['card_id']+'/text-assistance',json=dict(expected_revision=1,allow_external_processing=True))
    assert response.status_code==503,response.text
    error=response.json()['error']
    assert error['code']=='LLM_SCHEMA_REJECTED' and error['details']['upstream_status']==400
    assert 'secret-text' not in response.text and 'test-only' not in response.text
    assert 'LLM_SCHEMA_REJECTED' in caplog.text and 'upstream_status=400' in caplog.text
    assert 'secret-text' not in caplog.text and 'test-only' not in caplog.text
    assert client.get('/api/v1/cards/'+card['card_id']).json()==card

def test_legacy_empty_fields_can_be_selected_without_recreating_product(client):
    from backend.domain import blank
    card=create(client)
    name={k:v for k,v in card['fields'][0].items() if k!='label'}
    card['fields']=[name,*blank([])['fields'][1:]]
    with main.db() as conn:
        owner=conn.execute('SELECT session FROM objects WHERE id=?',(card['card_id'],)).fetchone()[0]
    main.save('card',card,owner)
    r=update(client,card,add_fields=[{'field_id':'material'}])
    assert r.status_code==200,r.text
    updated=r.json();field=next(f for f in updated['fields'] if f['field_id']=='material')
    assert field['label']=='Материал' and field['value'] is None
    assert updated['fields'][0]['value']=='Футболка' and updated['sources']==card['sources']
    checked=update(client,updated,field_updates=[dict(field_id=f['field_id'],value=f['value'],reviewed=bool(f['value'])) for f in updated['fields']]).json()
    assert not next(f for f in checked['fields'] if f['field_id']=='fat_percent').get('label')
