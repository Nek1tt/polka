"""Private product library, deletion integrity and human-readable export."""
import copy
from backend import main
from backend.domain import patch, now, uid
from test_presentation import client
from test_manual import create, upload


def test_library_is_private_and_excludes_ocr_results(client):
    card = create(client, {'product_name': '<script>Название</script>'})
    owner = client.cookies.get('card_session')
    analysis = copy.deepcopy(card)
    analysis['card_id'] = uid()
    main.save('card', analysis, owner)
    job = dict(job_id=uid(), result_card_id=analysis['card_id'], status='succeeded', expires_at=card['expires_at'])
    main.save('job', job, owner)
    foreign = copy.deepcopy(card)
    foreign['card_id'] = uid()
    main.save('card', foreign, 'different-session')
    data = client.get('/api/v1/cards').json()
    main.validate('CardList', data)
    ids = [item['card_id'] for item in data['cards']]
    assert card['card_id'] in ids and analysis['card_id'] not in ids and foreign['card_id'] not in ids
    assert next(item for item in data['cards'] if item['card_id'] == card['card_id'])['title'] == '<script>Название</script>'
    assert 'sources' not in data['cards'][0]


def test_delete_checks_owner_revision_active_ocr_and_removes_private_photos(client):
    card = upload(client, create(client, {'product_name': 'Удаляемый тест'}))
    owner = client.cookies.get('card_session')
    key = card['card_id']
    url = f'/api/v1/cards/{key}?expected_revision={card["revision"]}'
    assert client.delete(url, headers={'cookie': 'card_session=other'}).status_code == 404
    assert client.delete(f'/api/v1/cards/{key}?expected_revision=1').status_code == 409
    photo = main.PHOTOS / (card['photos'][0]['photo_id'] + '.png')
    job = dict(job_id=uid(), result_card_id=None, status='running', expires_at=card['expires_at'])
    main.save('job', job, owner)
    binding = dict(photo_id=job['job_id']+'-binding', base_card_id=key, photo_ids=[card['photos'][0]['photo_id']], expires_at=card['expires_at'])
    main.save('ocr_binding', binding, owner)
    assert client.delete(url).json()['error']['code'] == 'OCR_IN_PROGRESS'
    assert photo.exists() and client.get(f'/api/v1/cards/{key}').status_code == 200
    analysis = copy.deepcopy(card)
    analysis['card_id'] = uid()
    main.save('card', analysis, owner)
    job.update(status='succeeded', result_card_id=analysis['card_id'])
    main.save('job', job, owner)
    response = client.delete(url)
    assert response.status_code == 200
    main.validate('CardDeleted', response.json())
    assert not photo.exists()
    for deleted in [key, analysis['card_id']]:
        assert client.get('/api/v1/cards/'+deleted).status_code == 404
    with main.db() as conn:
        assert not conn.execute('SELECT id FROM objects WHERE id IN (?,?)', (job['job_id'], binding['photo_id'])).fetchall()
    assert client.delete(url).status_code == 404


def test_text_export_is_exact_confirmed_description_without_technical_data(client):
    card = create(client, {'product_name': 'Проверочная лампа', 'material': 'Металл'})
    url = '/api/v1/cards/'+card['card_id']
    assert client.get(url+'/export?format=text').status_code == 409
    card = client.patch(url, json=dict(expected_revision=card['revision'], field_updates=[dict(field_id=f['field_id'], value=f['value'], reviewed=True) for f in card['fields'] if f['value']])).json()
    card = client.patch(url, json=dict(expected_revision=card['revision'], description_update=dict(text=card['description']['text'], reviewed=True, asserted_as_user_input=False))).json()
    assert card['readiness']['state'] == 'ready_to_confirm'
    card = client.post(url+'/confirm', json=dict(expected_revision=card['revision'])).json()
    response = client.get(url+'/export?format=text')
    assert response.status_code == 200 and response.text == card['description']['text']+'\n'
    assert 'text/plain' in response.headers['content-type'] and '.txt' in response.headers['content-disposition']
    assert client.get(url+'/export').json() == card
    assert client.get(url+'/export?format=text', headers={'cookie':'card_session=other'}).status_code == 404
    assert client.get(url+'/export?format=html').status_code == 422
    card = client.patch(url, json=dict(expected_revision=card['revision'], field_updates=[dict(field_id='product_name', value='Изменённая лампа', reviewed=False)])).json()
    assert client.get(url+'/export?format=text').status_code == 409
