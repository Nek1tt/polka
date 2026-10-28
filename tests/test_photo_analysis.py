"""Fixture diagnostics test selection/TTL/projection, not OCR accuracy."""
import copy
from datetime import datetime, timedelta, timezone

from backend import main
from backend.domain import moderate, now, uid
from test_manual import create, upload
from test_presentation import client, validate_projection


def binding(client, card, quality, *, requested_at=None, status='succeeded', owner=None, expired=False):
    owner = owner or client.cookies.get('card_session')
    result = copy.deepcopy(card)
    result['card_id'] = uid()
    for photo in result['photos']:
        photo['quality'] = quality
    moderate(result)
    job = dict(job_id=uid(), ocr_mode='local', status=status, stage='done',
               result_card_id=result['card_id'], error=None, created_at=requested_at or now(),
               expires_at=card['expires_at'])
    link = dict(photo_id=job['job_id']+'-binding', base_card_id=card['card_id'],
                photo_ids=[p['photo_id'] for p in card['photos']], expires_at=card['expires_at'])
    if expired:
        job['expires_at'] = (datetime.now(timezone.utc)-timedelta(days=1)).isoformat()
    main.save('card', result, owner)
    main.save('job', job, owner)
    main.save('ocr_binding', link, owner)
    return job


def projected(client, card):
    response = client.get(f"/api/v1/cards/{card['card_id']}/recommendations", params={'expected_revision':card['revision']})
    assert response.status_code == 200, response.text
    data = response.json()
    validate_projection(data, 'CardRecommendations')
    return data


def test_photo_diagnostics_reach_review_without_changing_confirmed_card(client):
    card = upload(client, create(client, {'product_name':'Тестовая лампа'}))
    path = '/api/v1/cards/'+card['card_id']
    card = client.patch(path, json=dict(expected_revision=card['revision'], field_updates=[
        dict(field_id='product_name', value='Тестовая лампа', reviewed=True)])).json()
    card = client.patch(path, json=dict(expected_revision=card['revision'], description_update=dict(
        text=card['description']['text'], reviewed=True, asserted_as_user_input=False))).json()
    card = client.post(path+'/confirm', json={'expected_revision':card['revision']}).json()
    assert card['readiness']['state'] == 'confirmed'
    job = binding(client, card, 'unreadable')
    data = projected(client, card)
    assert data['photo_analysis']['job_id'] == job['job_id']
    assert data['photo_analysis']['photos'][0]['quality'] == 'unreadable'
    warning = next(r for r in data['recommendations'] if r['rule_id']=='unreadable_photos')
    assert warning['photo_ids'] == [card['photos'][0]['photo_id']]
    assert warning['card_revision'] == card['revision'] and warning['priority']=='warning'
    assert warning['source_ids'] == []
    assert set(warning['issue_ids']) <= {i['issue_id'] for i in data['photo_analysis']['issues']}
    assert data['readiness'] == card['readiness']
    assert client.get(path).json() == card
    assert client.get(path+'/export').json() == card
    assert client.get(path+'/recommendations', params={'expected_revision':card['revision']},
                      headers={'cookie':'card_session=foreign'}).status_code == 404


def test_latest_matching_success_ignores_foreign_failed_and_expired_jobs(client):
    card = upload(client, create(client))
    base = datetime.now(timezone.utc)
    stamp = lambda n: (base+timedelta(seconds=n)).isoformat()
    binding(client, card, 'unreadable', requested_at=stamp(-5))
    latest = binding(client, card, 'readable', requested_at=stamp(-4))
    binding(client, card, 'unreadable', requested_at=stamp(-3), status='failed')
    binding(client, card, 'unreadable', requested_at=stamp(-2), owner='foreign-owner')
    binding(client, card, 'unreadable', requested_at=stamp(-1), expired=True)
    data = projected(client, card)
    assert data['photo_analysis']['job_id'] == latest['job_id']
    assert data['photo_analysis']['issues'] == []
    assert not any(r['rule_id']=='unreadable_photos' for r in data['recommendations'])


def test_changed_fields_keep_photo_diagnostics_but_new_photos_invalidate_them(client):
    card = upload(client, create(client))
    job = binding(client, card, 'uncertain')
    path = '/api/v1/cards/'+card['card_id']
    card = client.patch(path, json=dict(expected_revision=card['revision'], field_updates=[
        dict(field_id='brand', value='Ручной бренд', reviewed=True)])).json()
    data = projected(client, card)
    assert data['photo_analysis']['job_id'] == job['job_id']
    assert any(r['rule_id']=='poor_photo' for r in data['recommendations'])
    card = upload(client, card)
    data = projected(client, card)
    assert data['photo_analysis'] is None
    assert not any(r['rule_id']=='poor_photo' for r in data['recommendations'])
    response = client.get(path+'/recommendations', params={'expected_revision':card['revision']-1})
    assert response.status_code == 409


def test_openapi_uses_current_origin_and_keeps_origin_protection(client):
    spec = client.get('/openapi.json').json()
    assert [s['url'] for s in spec['servers']] == ['/']
    assert client.post('/api/v1/cards', json={}, headers={'Origin':'https://foreign.invalid'}).status_code == 403
