"""Read-only projection and escaped HTML renderer, independent of frontend/."""
from copy import deepcopy
from html import escape
import re
from .catalog import get_template, category_profile, CATEGORY_LABELS, CatalogError
from .domain import LABELS, moderate, now, field_label

def preview(card, template_id, template_version):
    c = moderate(deepcopy(card))
    layout = get_template(template_id, template_version)
    category = c['category']['selected']
    if '*' not in layout['supported_categories'] and category not in layout['supported_categories']:
        raise CatalogError('TEMPLATE_INCOMPATIBLE', 'Шаблон не подходит к выбранной категории; категория карточки не изменена', 422)
    profile = category_profile(category)
    profile['fields'] = [dict(field_id=f['field_id'],label=field_label(f),required=f['required']) for f in c['fields']]
    fields = {f['field_id']: f for f in c['fields']}
    blocks = []
    for definition in layout['blocks']:
        b = dict(block_id=definition['block_id'], title=definition['title'], kind=definition['kind'],
                 fields=[], photos=[], description=None, category=None)
        if b['kind'] == 'fields':
            keys = [k for k in fields if k != 'product_name'] if definition['block_id']=='characteristics' else definition['field_ids']
            b['fields'] = [deepcopy(fields[k]) for k in keys if k in fields]
        if b['kind'] == 'photos': b['photos'] = deepcopy(c['photos'])
        if b['kind'] == 'description': b['description'] = deepcopy(c['description'])
        if b['kind'] == 'category': b['category'] = deepcopy(c['category'])
        blocks.append(b)
    return dict(schema_version='2.2', provider_mode=c['provider_mode'], card_id=c['card_id'], card_revision=c['revision'],
                template_id=layout['template_id'], template_version=layout['version'], template_name=layout['name'],
                is_draft=c['readiness']['state'] != 'confirmed', category_profile=profile, blocks=blocks,
                sources=deepcopy(c['sources']), readiness=deepcopy(c['readiness']),
                warnings=deepcopy(c['issues']), generated_at=now(), expires_at=c['expires_at'])

def e(value): return escape(str(value), quote=True)

def status_label(field):
    if field['status'] == 'conflict': return 'Противоречие — требуется решение'
    if field['value'] is None: return 'Не указано'
    return 'Проверено пользователем' if field['reviewed'] else 'Не проверено'

def evidence(source_ids, sources):
    parts = []
    for sid in source_ids:
        s = sources.get(sid)
        if not s: continue
        kind = {'ocr_text': 'С фотографии', 'user_input': 'Введено пользователем', 'classifier': 'Классификатор'}[s['kind']]
        parts.append(f'<li><b>{e(kind)}</b>: {e(s["text"])} <small>Источник {e(sid)}</small></li>')
    return '<details class="evidence"><summary>Источники</summary><ul>' + ''.join(parts) + '</ul></details>' if parts else ''

def field_html(f, sources):
    value = '<span class="missing">Не указано</span>' if f['value'] is None else e(f['value'])
    score = ''
    candidates = ''
    if f['status'] == 'conflict':
        candidates = '<details open><summary>Противоречащие значения</summary><ul>' + ''.join(
            '<li>' + e(candidate['value']) + evidence(candidate['source_ids'], sources) + '</li>' for candidate in f['candidates']) + '</ul></details>'
    return (f'<div class="fact {e(f["status"])}"><dt>{e(field_label(f))}'
            f'{" *" if f["required"] else ""}</dt><dd>{value}</dd><small>{e(status_label(f))}</small>'
            f'{score}{evidence(f["source_ids"], sources)}{candidates}</div>')

PALETTES = ('strata', 'ocean', 'sage', 'clay')


def render_html(p, palette='strata'):
    if palette not in PALETTES:
        raise CatalogError('PALETTE_NOT_FOUND', 'Палитра не найдена', 422)
    return marketplace_html(p, palette)


def marketplace_html(p, palette):
    sources = {s['source_id']: s for s in p['sources']}
    fields = {f['field_id']: f for b in p['blocks'] for f in b['fields']}
    photos = [photo for b in p['blocks'] for photo in b['photos']]
    title = fields.get('product_name', {}).get('value') or 'Название не указано'
    style = {'studio_v1':'studio', 'compact_v1':'compact'}.get(p['template_id'], 'market')
    state = 'Черновик · Не подтверждено' if p['is_draft'] else 'Подтверждено пользователем'
    mode = {'live':'Реальная обработка', 'fixture':'Тестовые результаты · вымышленные данные',
            'recorded_demo':'Записанный пример'}[p['provider_mode']]
    ready = p['readiness']
    thumbs, images = [], []
    for i, photo in enumerate(photos):
        url = '/api/v1/photos/' + photo['photo_id'] if re.fullmatch(r'[a-zA-Z0-9_-]+', photo['photo_id']) else ''
        thumbs.append(f'<button class="product-thumb" type="button" data-photo-index="{i}" aria-label="Фото {i+1}" aria-pressed="{"true" if i == 0 else "false"}"><img src="{e(url)}" alt="" width="56" height="72"></button>')
        images.append(f'<figure data-product-photo="{i}" {"hidden" if i else ""}><img src="{e(url)}" alt="Фото товара {i+1}" width="{photo["width"]}" height="{photo["height"]}" {"loading=lazy" if i else "fetchpriority=high"}><figcaption>Фото {i+1} из {len(photos)}</figcaption></figure>')
    gallery = '<div class="product-gallery"><div class="product-thumbs" aria-label="Фотографии">' + ''.join(thumbs) + '</div><div class="product-image">' + (''.join(images) or '<p>Добавьте фотографию товара</p>') + '</div></div>'
    category = p['category_profile']['label']
    category_data = next((b['category'] for b in p['blocks'] if b['category']), None)
    category_html = ''
    if category_data:
        category_html = '<details class="category-evidence"><summary>Источник категории и оценки</summary>' + evidence(category_data['source_ids'], sources)
        category_html += '<ul>' + ''.join(f'<li>{e(s["label"])}: {s["confidence"]["value"]:.2f}</li>' for s in category_data['scores']) + '</ul><small>Оценки классификатора не калиброваны. ' + ('Проверено пользователем' if category_data['reviewed'] else 'Не проверено') + '</small></details>'
    facts = '<dl class="product-facts">' + ''.join(field_html(f, sources) for key, f in fields.items() if key != 'product_name' and (f['value'] or f['required'])) + '</dl>'
    title_check = field_html(fields['product_name'], sources) if 'product_name' in fields else ''
    descriptions = []
    for b in p['blocks']:
        if b['description']:
            d = b['description']
            descriptions.append('<p class="product-copy">' + (e(d['text']) if d['text'] else 'Описание пока не сформировано. Проверьте исходные сведения.') + '</p><small>' + ('Проверено пользователем' if d['reviewed'] else 'Не проверено') + ' · ' + {'user':'Текст пользователя','template':'Шаблон из принятых полей','llm':'Внешняя модель'}[d['mode']] + '</small>' + evidence(d['source_ids'], sources))
    issues = ''.join('<li><strong>' + ('Нужно исправить: ' if i['severity'] == 'blocker' else 'Рекомендация: ') + e(i['message']) + '</strong><p>' + e(i['suggestion']) + '</p></li>' for i in p['warnings'])
    quantity = fields.get('net_quantity', {}).get('value')
    quantity_html = f'<div class="product-option"><span>Масса, объём или количество</span><strong>{e(quantity)}</strong><small>{e(status_label(fields["net_quantity"]))}</small></div>' if quantity else ''
    summary = f'<div class="product-info"><p class="product-category">{e(category)}</p><h2>{e(title)}</h2><p class="product-origin">Сведения из вашей карточки · ревизия {p["card_revision"]}</p>{quantity_html}<h3>О товаре</h3>{facts}{category_html}</div>'
    sidebar = f'''<aside class="product-review"><span class="product-status">{e(state)}</span><h3>Готовность карточки</h3><p class="product-count">{ready['required_filled']} <span>/ {ready['required_total']}</span></p><p>обязательных характеристик заполнено</p><progress max="{ready['required_total']}" value="{ready['required_filled']}" aria-label="Заполненность карточки"></progress><p class="product-note">Полнота данных не означает проверенность.</p><a class="secondary full" href="/">Вернуться в редактор</a><details class="product-moderation" open><summary>Предварительная модерация · {len(p['warnings'])}</summary><ul>{issues or '<li>Блокирующих замечаний нет.</li>'}</ul></details><p class="product-note">Правила прототипа, не решение маркетплейса. Подтверждение выполняется отдельно в редакторе.</p></aside>'''
    surface = f'''<article class="product-preview layout-{style}" data-layout="{style}"><div class="product-preview-top"><span>{e(p['template_name'])}</span><span>{e(mode)}</span></div><div class="product-layout">{gallery}{summary}{sidebar}</div><section class="product-description"><h3>Описание товара</h3>{''.join(descriptions)}<details><summary>Проверка названия и источники</summary><dl>{title_check}</dl></details></section></article>'''
    return f'''<!doctype html><html lang="ru" data-palette="{palette}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{e(title)} — предпросмотр</title><link rel="stylesheet" href="/style.css"><link rel="stylesheet" href="/presentation.css"><script type="module" src="/preview-page.mjs"></script></head><body class="preview-page"><a class="skip-link" href="#preview-main">К карточке товара</a><header><a class="brand" href="/"><span class="logo">п</span> полка</a><a class="secondary" href="/">Вернуться в редактор</a></header><main id="preview-main"><div class="preview-page-heading"><div><p>Предпросмотр сохранённой карточки</p><h1>{e(p['template_name'])}</h1></div><label>Палитра<select id="preview-palette"><option value="strata">Strata</option><option value="ocean">Морская</option><option value="sage">Шалфей</option><option value="clay">Терракота</option></select></label></div>{surface}<footer>Фотографии доступны только в вашей сессии до {e(p['expires_at'])}. Этот документ не является публичной ссылкой на товар.</footer></main></body></html>'''
