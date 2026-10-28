"""Manual-first behavior, provenance and protection against background overwrites."""
import json
import time
import jsonschema
from backend import main, cloud_ocr
from test_presentation import client

def create(client, fields=None):
    response = client.post('/api/v1/cards', json={'fields': fields or {}})
    assert response.status_code == 201, response.text
    card = response.json()
    jsonschema.validate(card, main.SCHEMA)
    return card

def upload(client, card):
    with (main.ROOT/'data/demo/cable.png').open('rb') as stream:
        response = client.post(f"/api/v1/cards/{card['card_id']}/photos", files={'files': ('cable.png', stream, 'image/png')}, data={'expected_revision': card['revision']})
    assert response.status_code == 200, response.text
    return response.json()

def test_manual_complete_path_without_a_model_or_photos(client, monkeypatch):
    def forbidden(*args):
        raise AssertionError('Manual work must not call OCR')
    monkeypatch.setattr(main.PROVIDERS, 'available', forbidden)
    card = create(client, {'product_name': 'Настольная лампа', 'material': 'Металл'})
    assert card['photos'] == [] and card['ocr']['provider'] == 'Not processed'
    assert not any(issue['rule_id'] == 'unreadable_photos' for issue in card['issues'])
    assert all(s['kind'] == 'user_input' and s['confidence'] is None for s in card['sources'])
    response = client.patch(f"/api/v1/cards/{card['card_id']}", json={'expected_revision': card['revision'], 'field_updates': [dict(field_id=f['field_id'], value=f['value'], reviewed=True) for f in card['fields'] if f['value']]})
    assert response.status_code == 200, response.text
    card = response.json()
    assert 'Настольная лампа' in card['description']['text'] and 'Металл' in card['description']['text']
    card = client.patch(f"/api/v1/cards/{card['card_id']}", json={'expected_revision': card['revision'], 'description_update': dict(text=card['description']['text'], reviewed=True, asserted_as_user_input=False)}).json()
    response = client.post(f"/api/v1/cards/{card['card_id']}/confirm", json={'expected_revision': card['revision']})
    assert response.status_code == 200, response.text
    card = response.json()
    assert card['readiness']['state'] == 'confirmed'
    assert client.get(f"/api/v1/cards/{card['card_id']}/export").status_code == 200
    preview = client.get(f"/api/v1/cards/{card['card_id']}/preview.html", params=dict(template_id='market_v1', template_version=1, expected_revision=card['revision']))
    assert preview.status_code == 200 and 'Добавьте фотографию товара' in preview.text

def test_upload_without_inference_and_stale_revision_is_atomic(client, monkeypatch):
    monkeypatch.setattr(main.PROVIDERS, 'available', lambda *_: (_ for _ in ()).throw(AssertionError('No OCR during upload')))
    original = create(client)
    card = upload(client, original)
    assert card['photos'][0]['quality'] == 'not_analyzed'
    assert not card['sources'] and not any(f['value'] for f in card['fields'])
    before = set(main.PHOTOS.iterdir())
    with (main.ROOT/'data/demo/cable.png').open('rb') as stream:
        result = client.post(f"/api/v1/cards/{card['card_id']}/photos", files={'files': ('x.png', stream, 'image/png')}, data={'expected_revision': original['revision']})
    assert result.status_code == 409 and set(main.PHOTOS.iterdir()) == before
    assert client.get(f"/api/v1/cards/{card['card_id']}").json() == card

def test_real_background_ocr_keeps_manual_edits_and_accepts_only_one_source(client):
    card = upload(client, create(client, {'product_name': 'Ручное название', 'brand': 'Мой бренд'}))
    response = client.post(f"/api/v1/cards/{card['card_id']}/ocr-jobs", json=dict(expected_revision=card['revision'], ocr_mode='local'))
    assert response.status_code == 202, response.text
    job_id = response.json()['job_id']
    card = client.patch(f"/api/v1/cards/{card['card_id']}", json=dict(expected_revision=card['revision'], field_updates=[dict(field_id='brand', value='Изменено во время OCR', reviewed=True)])).json()
    for _ in range(250):
        job = client.get('/api/v1/jobs/'+job_id).json()
        if job['status'] in ('succeeded', 'failed'):
            break
        time.sleep(.1)
    assert job['status'] == 'succeeded', job
    assert client.get(f"/api/v1/cards/{card['card_id']}").json() == card
    response = client.get(f"/api/v1/cards/{card['card_id']}/ocr-suggestions", params={'job_id': job_id})
    assert response.status_code == 200, response.text
    data = response.json()
    main.validate('CardSuggestions', data)
    line = next(row for row in data['review']['lines'] if row['field_id'] == 'brand')
    payload = dict(expected_revision=card['revision'], job_id=job_id, field_id='brand', source_ids=line['source_ids'])
    url = f"/api/v1/cards/{card['card_id']}/accept-suggestion"
    assert client.post(url, json={**payload, 'source_ids': ['invented']}).status_code == 422
    assert client.post(url, json=payload).json()['error']['code'] == 'FIELD_HAS_VALUE'
    assert client.get(f"/api/v1/cards/{card['card_id']}").json() == card
    assert client.post(url, json={**payload, 'expected_revision': card['revision']-1, 'replace_existing': True}).status_code == 409
    other = create(client)
    assert client.get(f"/api/v1/cards/{other['card_id']}/ocr-suggestions", params={'job_id': job_id}).status_code == 404
    assert client.get(f"/api/v1/cards/{card['card_id']}/ocr-suggestions", params={'job_id': job_id}, headers={'cookie': 'card_session=someone-else'}).status_code == 404
    response = client.post(url, json={**payload, 'replace_existing': True})
    assert response.status_code == 200, response.text
    accepted = response.json()
    field = next(f for f in accepted['fields'] if f['field_id'] == 'brand')
    assert field['value'] == 'Example' and not field['reviewed']
    assert field['confidence'] and field['confidence']['calibrated'] is False
    assert next(f for f in accepted['fields'] if f['field_id']=='product_name')['value'] == 'Ручное название'
    assert any(c['value']=='Изменено во время OCR' for c in field['candidates'])
    sources = {s['source_id']: s for s in accepted['sources']}
    assert all(sources[sid]['kind']=='ocr_text' and sources[sid]['photo_id']==card['photos'][0]['photo_id'] for sid in field['source_ids'])
    assert all(dep in sources for s in sources.values() for dep in s['input_source_ids'])
    assert client.get(f"/api/v1/cards/{card['card_id']}/export").status_code == 409

def test_unconfigured_api_does_not_change_draft(client, monkeypatch):
    monkeypatch.setattr(cloud_ocr, 'configured', lambda: False)
    card = upload(client, create(client))
    response = client.post(f"/api/v1/cards/{card['card_id']}/ocr-jobs", json=dict(expected_revision=card['revision'], ocr_mode='api'))
    assert response.status_code == 503
    assert client.get(f"/api/v1/cards/{card['card_id']}").json() == card
    assert client.post('/api/v1/cards', json={'fields': {'imaginary': 'fact'}}).status_code == 422
