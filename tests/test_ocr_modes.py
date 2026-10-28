"""Provider routing, external consent, literal parsing and absence of barcode APIs."""
import copy
import json
import time
import httpx
import pytest
from backend import main, cloud_ocr
from backend.domain import LABELS
from backend.inference import Providers
from test_presentation import client


def test_no_barcode_fields_routes_or_contracts(client):
    assert 'barcode' not in LABELS
    doc=client.get('/openapi.json').json()
    assert not any('catalog-lookup' in path or 'catalog-apply' in path for path in doc['paths'])
    assert not any(key.startswith('Catalog') for key in doc['components']['schemas'])
    assert 'barcode' not in doc['components']['schemas']['InitialData']['properties']['fields']['properties']
    assert client.post('/api/v1/cards/anything/catalog-lookup',json={}).status_code in (404,405)
    main.validate('Health',client.get('/health/ready').json())


def test_api_not_configured_fails_before_photo_storage(client,monkeypatch):
    monkeypatch.delenv('GOOGLE_VISION_API_KEY',raising=False)
    def forbidden(*args):raise AssertionError('No external requests without explicit configured mode')
    monkeypatch.setattr(cloud_ocr,'recognize',forbidden)
    config=client.get('/api/v1/config').json()
    assert [m['id'] for m in config['ocr_modes']]==['local','api']
    assert not config['ocr_modes'][1]['available'] and config['ocr_modes'][1]['sends_photos']
    with (main.ROOT/'data/demo/cable.png').open('rb') as f:
        r=client.post('/api/v1/jobs',files={'files':('test.png',f,'image/png')},data={'initial_data':json.dumps({'ocr_mode':'api'})})
    assert r.status_code==503 and r.json()['error']['code']=='PROVIDER_UNAVAILABLE'


def test_local_mode_never_calls_cloud_even_with_a_key(client,monkeypatch):
    from test_service import submit
    monkeypatch.setenv('GOOGLE_VISION_API_KEY','test-placeholder')
    def forbidden(*args):raise AssertionError('Local mode must not send photos')
    monkeypatch.setattr(cloud_ocr,'recognize',forbidden)
    card,job=submit(client,'cable',{'ocr_mode':'local'})
    assert job['ocr_mode']=='local' and card['ocr']['mode']=='local'
    assert 'PP-OCRv5' in card['ocr']['provider']
    assert card['fields'][0]['value']=='USB cable'
    with (main.ROOT/'data/demo/cable.png').open('rb') as f:
        r=client.post('/api/v1/jobs',files={'files':('test.png',f,'image/png')},data={'initial_data':json.dumps({'ocr_mode':'anything'})})
    assert r.status_code==422


def test_explicit_api_routes_to_cloud_and_preserves_unreviewed_provenance(client,monkeypatch):
    monkeypatch.setenv('GOOGLE_VISION_API_KEY','test-placeholder')
    calls=[]
    def cloud(path):
        calls.append(path)
        return [dict(text=text,confidence=.98,bbox=[.1,i*.15+.1,.9,i*.15+.2],words=[])
                for i,text in enumerate(['Product: Test lamp','Brand: Example','Color: Blue'])]
    monkeypatch.setattr(cloud_ocr,'recognize',cloud)
    monkeypatch.setattr(main.PROVIDERS,'ready',False)
    with (main.ROOT/'data/demo/cable.png').open('rb') as f:
        r=client.post('/api/v1/jobs',files={'files':('test.png',f,'image/png')},data={'initial_data':json.dumps({'ocr_mode':'api'})})
    assert r.status_code==202,r.text
    assert r.json()['ocr_mode']=='api'
    for _ in range(100):
        job=client.get('/api/v1/jobs/'+r.json()['job_id']).json()
        if job['status'] in ('failed','succeeded'):break
        time.sleep(.05)
    assert job['status']=='succeeded',job
    card=client.get('/api/v1/cards/'+job['result_card_id']).json()
    assert calls and card['ocr']['mode']=='api'
    assert card['fields'][0]['value']=='Test lamp' and not card['fields'][0]['reviewed']
    assert card['confirmation'] is None
    assert all('Google Cloud Vision' in s['confidence']['provider'] for s in card['sources'])
    assert not client.get('/api/v1/cards/'+card['card_id']+'/export').is_success


def word(text,x=10,end='LINE_BREAK',confidence=.91):
    return dict(confidence=confidence,boundingBox={'vertices':[{'x':x,'y':10},{'x':x+30,'y':10},{'x':x+30,'y':20},{'x':x,'y':20}]},
                symbols=[{'text':c,**({'property':{'detectedBreak':{'type':end}}} if i==len(text)-1 else {})} for i,c in enumerate(text)])


def payload(words):
    return {'responses':[{'fullTextAnnotation':{'pages':[{'width':100,'height':100,'blocks':[{'paragraphs':[{'words':words}]}]}]}}]}


def test_cloud_parser_uses_literal_symbols_line_breaks_and_real_scores():
    data=payload([word('Brand:',end='SPACE'),word('3M',x=50),word('330ml')]);before=copy.deepcopy(data)
    lines=cloud_ocr.parse_response(data)
    assert data==before
    assert [l['text'] for l in lines]==['Brand: 3M','330ml']
    assert lines[0]['confidence']==pytest.approx(.91)
    assert lines[0]['bbox']==[.1,.1,.8,.2]
    assert cloud_ocr.parse_response({'responses':[{}]})==[]
    with pytest.raises(RuntimeError):cloud_ocr.parse_response({'responses':[{'error':{'code':403}}]})
    with pytest.raises(ValueError):cloud_ocr.parse_response(payload([word('bad',confidence=float('nan'))]))


def test_cloud_request_is_fixed_host_bounded_explicit_and_no_retries(monkeypatch):
    monkeypatch.setenv('GOOGLE_VISION_API_KEY','test-placeholder')
    seen=[];original=httpx.Client
    def handler(request):
        seen.append(request)
        assert str(request.url)==cloud_ocr.ENDPOINT
        assert request.headers['X-Goog-Api-Key']=='test-placeholder'
        sent=json.loads(request.content)['requests'][0]
        assert sent['features']==[{'type':'DOCUMENT_TEXT_DETECTION'}]
        assert sent['imageContext']['languageHints']==['ru','en']
        assert sent['image']['content'] and 'source' not in sent['image']
        return httpx.Response(200,json=payload([word('Example')]))
    monkeypatch.setattr(httpx,'Client',lambda **kwargs:original(transport=httpx.MockTransport(handler),**kwargs))
    assert cloud_ocr.recognize(main.ROOT/'data/demo/cable.png')[0]['text']=='Example'
    assert len(seen)==1
