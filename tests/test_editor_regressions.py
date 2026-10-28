"""Regressions reported with a typed, checked but unsaved product name."""
import copy
from backend import main
from test_presentation import client

def create(client, **data):
    response=client.post('/api/v1/cards',json=data)
    assert response.status_code==201,response.text
    return response.json()

def test_saving_reviewed_name_updates_recommendations_and_survives_reload(client):
    card=create(client);path='/api/v1/cards/'+card['card_id']
    response=client.patch(path,json=dict(expected_revision=card['revision'],field_updates=[
        dict(field_id='product_name',value='Футболка (Фуфайка)',reviewed=True)]))
    assert response.status_code==200,response.text
    card=response.json();field=card['fields'][0]
    assert field['reviewed'] and field['status']=='accepted'
    data=client.get(path+'/recommendations',params={'expected_revision':card['revision']}).json()
    assert not any('product_name' in r['field_ids'] for r in data['recommendations'])
    assert card['readiness']['required_total']==1 and card['readiness']['required_filled']==1
    assert client.get(path).json()==card

def test_optional_characteristics_cannot_become_required_through_legacy_api(client):
    card=create(client,fields={'product_name':'Мяч'},required_fields=['manufacturer'])
    path='/api/v1/cards/'+card['card_id']
    assert card['readiness']['missing_fields']==[]
    assert next(f for f in card['fields'] if f['field_id']=='manufacturer')['required'] is False
    response=client.patch(path,json=dict(expected_revision=card['revision'],
        add_fields=[dict(label='Обхват рукоятки',required=True)],
        field_updates=[dict(field_id='manufacturer',value=None,reviewed=False,required=True),dict(field_id='product_name',value='Мяч',reviewed=True,required=False)]))
    assert response.status_code==200,response.text
    card=response.json()
    assert card['readiness']['required_total']==1 and card['readiness']['missing_fields']==[]
    assert all(f['required']==(f['field_id']=='product_name') for f in card['fields'])

def test_empty_name_cannot_become_reviewed_or_confirmed(client):
    card=create(client);path='/api/v1/cards/'+card['card_id']
    card=client.patch(path,json=dict(expected_revision=card['revision'],field_updates=[dict(field_id='product_name',value=None,reviewed=True)])).json()
    assert card['fields'][0]['reviewed'] is False
    assert card['readiness']['missing_fields']==['product_name']
    assert client.post(path+'/confirm',json={'expected_revision':card['revision']}).status_code==409

def test_startup_migrates_old_requirements_once_without_losing_facts_or_review(client):
    card=create(client,fields={'product_name':'Футболка','material':'Хлопок'})
    path='/api/v1/cards/'+card['card_id']
    card=client.patch(path,json=dict(expected_revision=card['revision'],field_updates=[dict(field_id=f['field_id'],value=f['value'],reviewed=True) for f in card['fields']])).json()
    card=client.patch(path,json=dict(expected_revision=card['revision'],description_update=dict(text=card['description']['text'],reviewed=True,asserted_as_user_input=False))).json()
    card=client.post(path+'/confirm',json={'expected_revision':card['revision']}).json()
    before=copy.deepcopy(card)
    card['fields'][1]['required']=True
    with main.db() as conn:
        owner=conn.execute('SELECT session FROM objects WHERE id=?',(card['card_id'],)).fetchone()[0]
    main.save('card',card,owner)
    main.initialize()
    changed=client.get(path).json()
    assert changed['revision']==before['revision']+1 and changed['confirmation'] is None
    assert changed['description']==before['description'] and changed['sources']==before['sources']
    assert changed['fields'][1]['value']=='Хлопок' and changed['fields'][1]['reviewed']
    assert changed['fields'][1]['required'] is False
    assert changed['readiness']['required_total']==1 and changed['readiness']['state']=='ready_to_confirm'
    main.initialize()
    assert client.get(path).json()==changed
