"""All presentation alternatives must preserve evidence, unknowns and revision guards."""
import copy
import pytest
from backend.preview import preview, render_html, PALETTES
from backend.catalog import CatalogError
from test_presentation import client, seed, query


@pytest.mark.parametrize('category', ['dairy', 'jam', 'unknown'])
def test_three_layouts_use_same_facts_and_never_write(client, category):
    card, owner = seed(client, 'needs_review_conflict')
    card['category']['selected'] = category
    from backend import main
    main.save('card', card, owner)
    original = copy.deepcopy(card)
    field_sets = []
    for tid, css in [('market_v1','market'), ('studio_v1','studio'), ('compact_v1','compact')]:
        p = preview(card, tid, 1)
        field_sets.append({f['field_id']: f for b in p['blocks'] for f in b['fields']})
        for palette in PALETTES:
            r = client.get('/api/v1/cards/'+card['card_id']+'/preview.html', params={**query(card, tid), 'palette':palette})
            assert r.status_code == 200
            assert f'data-layout="{css}"' in r.text
            assert f'data-palette="{palette}"' in r.text
            assert 'Противоречие' in r.text and 'Тестовые результаты' in r.text
            assert 'В корзину' not in r.text and '524 903' not in r.text
    assert field_sets[0] == field_sets[1] == field_sets[2]
    assert card == original
    assert client.get('/api/v1/cards/'+card['card_id']).json() == original


def test_palette_is_allowlisted_and_private_revision_checks_still_apply(client):
    card, _ = seed(client)
    path = '/api/v1/cards/'+card['card_id']+'/preview.html'
    assert client.get(path, params={**query(card, 'market_v1'),'palette':'<script>'}).status_code == 422
    assert client.get(path, params={**query(card, 'market_v1'),'expected_revision':card['revision']+1}).status_code == 409
    with pytest.raises(CatalogError):
        render_html(preview(card, 'market_v1', 1), 'unknown')
