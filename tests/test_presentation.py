import copy
import json
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
import pytest
import jsonschema
from fastapi.testclient import TestClient
from backend import main
from backend.catalog import category_profile, get_template
from backend.domain import LABELS, REQUIRED, source, moderate, patch
from backend.preview import preview
from backend.recommendations import recommendations

ROOT = main.ROOT
BUNDLE = json.loads((ROOT/'contracts/presentation.schema.json').read_text(encoding='utf-8'))

def validate_projection(value, name):
    jsonschema.validate(value, {'$ref':'#/$defs/'+name, '$defs':BUNDLE['$defs']})

@pytest.fixture(scope='module')
def client():
    with TestClient(main.app, headers={'Origin':'http://localhost:8000'}) as c:
        yield c

def seed(client, name='needs_information', *, expired=False):
    c = json.loads((ROOT/f'contracts/examples/{name}.json').read_text(encoding='utf-8'))
    c['card_id'] = secrets.token_hex(16)
    c['expires_at'] = (datetime.now(timezone.utc)+timedelta(days=-1 if expired else 1)).isoformat()
    owner = secrets.token_urlsafe(24)
    client.cookies.set('card_session', owner)
    main.save('card', c, owner)
    return c, owner

def query(c, tid='universal_v1'):
    return {'template_id':tid, 'template_version':1, 'expected_revision':c['revision']}

def test_catalog_versions_and_single_domain_rules(client):
    version=client.get('/api/v1/version').json()
    from backend.version import API_VERSION
    assert version['api_version']==API_VERSION and version['features']['templates']
    assert version['editor_integration']['template_selector'] is True
    r = client.get('/api/v1/templates')
    assert r.status_code == 200
    data = r.json(); validate_projection(data, 'TemplateCatalog')
    assert {t['template_id'] for t in data['templates']} == {'universal_v1','market_v1','studio_v1','compact_v1'}
    for t in data['templates']:
        validate_projection(t,'CardTemplate')
        assert t['description_styles'] == ['structured']
        assert 'value' not in json.dumps(t) and '250' not in json.dumps(t)
        r = client.get('/api/v1/templates/'+t['template_id'],params={'version':1})
        assert r.json() == t
    assert client.get('/api/v1/templates/not-real',params={'version':1}).status_code == 404
    assert client.get('/api/v1/templates/market_v1',params={'version':2}).json()['error']['code'] == 'TEMPLATE_VERSION_NOT_FOUND'
    assert client.get('/api/v1/templates/market_v1').status_code == 422
    a=get_template('market_v1',1);a['blocks'][0]['title']='mutated'
    assert get_template('market_v1',1)['blocks'][0]['title']!='mutated'
    for profile in data['category_profiles']:
        assert {f['field_id'] for f in profile['fields'] if f['required']} == set(REQUIRED)
        assert all(LABELS[f['field_id']]==f['label'] for f in profile['fields'])

@pytest.mark.parametrize('name',['needs_information','needs_review_conflict','ready_to_confirm','confirmed'])
def test_preview_states_provenance_and_no_writes(client,name):
    c,owner = seed(client,name)
    before = client.get('/api/v1/cards/'+c['card_id']).json()
    path='/api/v1/cards/'+c['card_id']
    r=client.get(path+'/preview',params=query(c))
    assert r.status_code == 200,r.text
    p=r.json();validate_projection(p,'CardPreview')
    assert p['is_draft'] == (name!='confirmed')
    assert p['provider_mode']=='fixture'
    assert p['card_revision']==c['revision']
    assert p['readiness']==moderate(copy.deepcopy(c))['readiness']
    original={f['field_id']:f for f in c['fields']}
    for b in p['blocks']:
        for f in b['fields']:
            assert f == original[f['field_id']]
            assert set(f['source_ids']) <= {s['source_id'] for s in p['sources']}
        if b['description']:assert b['description']==c['description']
    html=client.get(path+'/preview.html',params=query(c))
    assert html.status_code==200
    assert 'text/html' in html.headers['content-type'] and html.headers['cache-control']=='no-store'
    assert "script-src 'self'" in html.headers['content-security-policy']
    assert 'Тестовые результаты' in html.text
    assert ('Не подтверждено' in html.text)==(name!='confirmed')
    assert client.get(path).json()==before
    if name!='confirmed':assert client.get(path+'/export').status_code==409

def test_universal_layouts_do_not_require_categories_or_invent_values(client):
    c,owner=seed(client)
    c['category'].update(selected='Электроника / любой свободный текст',reviewed=True)
    main.save('card',c,owner)
    path='/api/v1/cards/'+c['card_id']
    for tid in ('universal_v1','market_v1','studio_v1','compact_v1'):
        r=client.get(path+'/preview',params=query(c,tid))
        assert r.status_code==200,r.text
        assert r.json()['category_profile']['supported']
        assert next(f for b in r.json()['blocks'] for f in b['fields'] if f['field_id']=='material')['value'] is None
    c['category']['selected']='unknown';main.save('card',c,owner)
    p=client.get(path+'/preview',params=query(c)).json()
    assert 'category' not in p['readiness']['missing_fields']

def test_private_expired_and_revision_guards(client):
    c,owner=seed(client);path='/api/v1/cards/'+c['card_id']
    for suffix in ('/preview','/preview.html','/recommendations'):
        params=query(c);params['expected_revision']=c['revision']+1
        assert client.get(path+suffix,params=params).status_code==409
        assert client.get(path+suffix).status_code==422
        with TestClientWithoutLifespan() as stranger:
            assert stranger.get(path+suffix,params=query(c)).status_code==404
    expired,_=seed(client,expired=True)
    for suffix in ('/preview','/preview.html','/recommendations'):
        assert client.get('/api/v1/cards/'+expired['card_id']+suffix,params=query(expired)).status_code==404

class TestClientWithoutLifespan:
    def __enter__(self):self.client=TestClient(main.app);return self.client
    def __exit__(self,*args):self.client.close()

def test_html_escapes_all_user_values_and_private_image_urls(client):
    c,owner=seed(client)
    attack='<script>alert("x")</script><img src="https://evil.invalid/pixel" onerror="alert(1)">'
    f=c['fields'][0];f['value']=attack
    sid=source(c,attack);f['source_ids']=[sid]
    f['candidates'].append({'value':attack,'source_ids':[sid],'confidence':None});f['status']='conflict'
    c['description'].update(text=attack,mode='user',reviewed=False,source_ids=[sid],statements=[{'text':attack,'source_ids':[sid],'asserted_as_user_input':False}])
    c['photos'][0]['url']='https://evil.invalid/image'
    main.save('card',c,owner)
    r=client.get('/api/v1/cards/'+c['card_id']+'/preview.html',params=query(c))
    assert r.status_code==200
    assert '<script>alert' not in r.text and '<img src="https://' not in r.text
    assert '&lt;script&gt;' in r.text and 'src="/api/v1/photos/' in r.text

def test_recommendations_are_prioritized_and_resolved_by_patch(client):
    c,owner=seed(client,'needs_review_conflict');before=copy.deepcopy(c)
    result=recommendations(c);validate_projection(result,'CardRecommendations')
    assert c==before
    items=result['recommendations']
    assert items[0]['rule_id']=='unresolved_conflict'
    conflict=next(r for r in items if r['rule_id']=='unresolved_conflict' and r['field_ids']==['net_quantity'])
    assert len(conflict['candidates'])>=2
    assert set(conflict['source_ids']) >= {sid for candidate in conflict['candidates'] for sid in candidate['source_ids']}
    assert all(r['rule_id']!='unreviewed_value' for r in items if r['field_ids']==['net_quantity'])
    path='/api/v1/cards/'+c['card_id']
    r=client.get(path+'/recommendations',params={'expected_revision':c['revision']})
    assert r.status_code==200
    assert client.get(path).json()==before
    r=client.patch(path,json={'expected_revision':c['revision'],'field_updates':[{'field_id':'net_quantity','value':'250 г','reviewed':True,'resolve_conflict':True}]})
    assert r.status_code==200,r.text
    updated=r.json()
    current=client.get(path+'/recommendations',params={'expected_revision':updated['revision']}).json()
    assert all(not (x['rule_id']=='unresolved_conflict' and x['field_ids']==['net_quantity']) for x in current['recommendations'])
    assert updated['confirmation'] is None

def test_missing_questions_stable_ids_and_low_score_review(client):
    c,owner=seed(client)
    result=recommendations(c);validate_projection(result,'CardRecommendations')
    missing=next(r for r in result['recommendations'] if r['rule_id']=='missing_required')
    assert missing['question'] and missing['priority']=='blocker'
    prior={r['recommendation_id'] for r in result['recommendations']}
    c['revision']+=1
    assert {r['recommendation_id'] for r in recommendations(c)['recommendations']}==prior
    f=c['fields'][0];f['value']='Название для проверки';f['confidence']={'value':0.2,'kind':'ocr_aggregate','provider':'test','calibrated':False};f['reviewed']=False
    assert any(r['rule_id']=='low_ocr_score' for r in recommendations(c)['recommendations'])
    f['reviewed']=True
    assert not any(r['rule_id']=='low_ocr_score' and r['field_ids']==[f['field_id']] for r in recommendations(c)['recommendations'])
    assert f['confidence']['value']==0.2
    assert any(i['rule_id']=='low_ocr_score' for i in moderate(copy.deepcopy(c))['issues'])

def test_recommendation_photos_are_concrete_and_no_extra_score(client):
    c,_=seed(client)
    for p in c['photos']:p['quality']='unreadable'
    result=recommendations(c)
    r=next(r for r in result['recommendations'] if r['rule_id']=='unreadable_photos')
    assert r['photo_ids']==[p['photo_id'] for p in c['photos']]
    assert 'не доказывает размытость' in r['action']
    assert 'score' not in result and 'quality_score' not in result
    assert set(r['source_ids'])<={s['source_id'] for s in c['sources']}

def test_openapi_new_contracts_match_bundle_and_all_gets(client):
    doc=client.get('/openapi.json').json()
    for name in ('TemplateCatalog','CardTemplate','CardPreview','CardRecommendations','Recommendation','PhotoAnalysis'):
        expected=json.loads(json.dumps(BUNDLE['$defs'][name]).replace('#/$defs/','#/components/schemas/'))
        assert doc['components']['schemas'][name]==expected
    for path in ('/api/v1/templates','/api/v1/templates/{template_id}','/api/v1/cards/{card_id}/preview','/api/v1/cards/{card_id}/preview.html','/api/v1/cards/{card_id}/recommendations'):
        assert set(doc['paths'][path])=={'get'}
    for filename,name in [('templates.json','TemplateCatalog'),('preview-incomplete.json','CardPreview'),('preview-confirmed.json','CardPreview'),('recommendations-conflict.json','CardRecommendations'),('recommendations-photo-analysis.json','CardRecommendations')]:
        data=json.loads((ROOT/'contracts/presentation-examples'/filename).read_text(encoding='utf-8'))
        validate_projection(data,name)
        if filename!='templates.json':assert data['provider_mode']=='fixture'
