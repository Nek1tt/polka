"""Searchable suggestions, not a mandatory product schema."""
from .domain import LABELS, normalized, uid

EXTRA = {'size': 'Размер', 'weight': 'Вес', 'sport': 'Вид спорта', 'gender': 'Пол',
         'age_group': 'Возрастная группа', 'season': 'Сезон', 'country': 'Страна изготовления',
         'care': 'Уход', 'power': 'Мощность', 'capacity': 'Вместимость',
         'package_contents': 'Комплектация', 'warranty': 'Гарантия', 'compatibility': 'Совместимость'}
CATALOG = {**LABELS, **EXTRA}

def new_field(key, label=None, required=False):
    return dict(field_id=key, label=label or CATALOG.get(key, key), value=None,
                required=key == 'product_name', status='missing', reviewed=False,
                source_ids=[], confidence=None, candidates=[])

def change_fields(card, payload):
    fields = {f['field_id']: f for f in card['fields']}
    removed = payload.get('remove_fields', [])
    if 'product_name' in removed:
        raise ValueError('Название товара нельзя удалить')
    if any(key not in fields for key in removed):
        raise ValueError('Удаляемая характеристика отсутствует в карточке')
    if set(removed) & {u['field_id'] for u in payload.get('field_updates', [])}:
        raise ValueError('Нельзя одновременно изменить и удалить характеристику')
    for key in removed:
        del fields[key]
    for definition in payload.get('add_fields', []):
        key = definition.get('field_id') or 'custom_' + uid()
        label = (definition.get('label') or CATALOG.get(key, '')).strip()
        legacy=fields.get(key)
        if legacy and not legacy.get('label') and not legacy['value'] and not legacy['required'] and key in CATALOG:
            legacy['label']=CATALOG[key]
            continue
        if not label or key in fields or any(normalized(f.get('label') or CATALOG.get(f['field_id'], f['field_id'])) == normalized(label) for f in fields.values()):
            raise ValueError('Укажите уникальное название новой характеристики')
        fields[key] = new_field(key, label, definition.get('required', False))
    if len(fields) > 80:
        raise ValueError('В карточке может быть до 80 характеристик')
    if any(u['field_id'] not in fields for u in payload.get('field_updates', [])):
        raise ValueError('Сначала добавьте характеристику в карточку')
    card['fields'] = list(fields.values())
