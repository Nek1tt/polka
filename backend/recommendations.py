"""Actionable projections of domain Issues. No independent readiness score."""
from copy import deepcopy
import hashlib
from .domain import LABELS, moderate, now, field_label

QUESTIONS = {
    'product_name': 'Какое название товара указано на упаковке?',
    'net_quantity': 'Какая масса нетто или объём указаны на упаковке, включая единицу?',
    'ingredients': 'Какой полный состав указан на упаковке?',
    'storage_conditions': 'Какие условия хранения указаны на упаковке?',
    'shelf_life': 'Какой срок годности указан на упаковке?',
    'manufacturer': 'Какой производитель указан на упаковке?',
    'fat_percent': 'Какая жирность указана на упаковке?',
    'category': 'Какой тип товара вы хотите указать? Это необязательное поле.',
}
ORDER = {'unresolved_conflict': 0, 'missing_required': 1, 'unreadable_photos': 2,
         'unreviewed_value': 3, 'unsupported_claim': 4, 'description_needs_review': 5,
         'low_ocr_score': 6, 'poor_photo': 7, 'low_resolution':7, 'optional_missing': 8}

def recommendations(card):
    c = moderate(deepcopy(card))
    fields = {f['field_id']: f for f in c['fields']}
    conflict_fields = {key for i in c['issues'] if i['rule_id'] == 'unresolved_conflict' for key in i['field_ids']}
    grouped = {}
    for issue in c['issues']:
        rule = issue['rule_id']
        keys = issue['field_ids']
        if rule == 'low_ocr_score' and keys and fields.get(keys[0], {}).get('reviewed'):
            continue  # original warning remains; repeated manual review isn't a useful action
        if rule in ('unreviewed_value', 'low_ocr_score') and any(k in conflict_fields for k in keys):
            rule = 'unresolved_conflict'
        target = (rule, tuple(sorted(keys)), tuple(sorted(issue['photo_ids'])))
        grouped.setdefault(target, []).append(issue)
    items = []
    for (rule, field_ids, photo_ids), issues in grouped.items():
        key = field_ids[0] if field_ids else None
        field = fields.get(key)
        area = 'photos' if rule in ('unreadable_photos', 'poor_photo', 'low_resolution') else 'text' if key == 'description' else 'category' if key == 'category' else 'characteristics'
        primary = next((i for i in issues if i['rule_id'] == rule), issues[0])
        action = primary['suggestion']
        question = None
        candidates = []
        if rule == 'unresolved_conflict':
            action_type = 'resolve_conflict'
            question = f'Какое значение поля «{field_label(field) if field else "Описание" }» верно? Сравните источники.'
            if field:
                candidates = deepcopy(field['candidates'])
            if key == 'description': question = 'Как исправить описание, чтобы оно согласовывалось с характеристиками?'
        elif rule in ('missing_required', 'optional_missing'):
            action_type = 'provide_information' if rule == 'missing_required' else 'enrich_optional'
            question = QUESTIONS.get(key)
            if key == 'category': action = 'Укажите тип товара свободным текстом или оставьте поле пустым.'
        elif rule == 'unreviewed_value':
            action_type = 'review_value'
            question = 'Верно ли определена категория?' if key == 'category' else f'Совпадает ли «{field_label(field) if field else key}» с источником?'
        elif rule == 'description_needs_review':
            action_type = 'review_description'
            action = ('Сначала проверьте характеристики, затем пересоберите и проверьте описание.'
                      if any(f['value'] and not f['reviewed'] for f in c['fields'])
                      else 'Проверьте описание по принятым фактам. Свой текст подтвердите как пользовательские исходные сведения либо пересоберите шаблон.')
            question = 'Соответствует ли текущее описание принятым фактам?'
        elif rule == 'unreadable_photos':
            action_type = 'verify_photo'
            photo_ids = tuple(p['photo_id'] for p in c['photos'])
            action = 'Заполните сведения вручную или добавьте крупное фото надписи. Отсутствие OCR-текста не доказывает размытость фотографии.'
        elif rule in ('poor_photo', 'low_ocr_score', 'low_resolution', 'missing_photos'):
            action_type = 'verify_photo' if rule in ('poor_photo','low_resolution','missing_photos') else 'review_value'
        else:
            action_type = 'review_description'
        sids = []
        if field:
            sids.extend(field['source_ids'])
            for candidate in candidates: sids.extend(candidate['source_ids'])
        elif key == 'category': sids.extend(c['category']['source_ids'])
        elif key == 'description': sids.extend(c['description']['source_ids'])
        sids.extend(s['source_id'] for s in c['sources'] if s['photo_id'] in photo_ids)
        identity = '|'.join([rule, *sorted(field_ids), *sorted(photo_ids)])
        items.append(dict(recommendation_id=hashlib.sha256(identity.encode()).hexdigest()[:24],
                          card_revision=c['revision'], rule_id=rule,
                          priority='blocker' if any(i['severity'] == 'blocker' for i in issues) else 'warning',
                          area=area, action_type=action_type, reason=primary['message'], action=action,
                          field_ids=list(field_ids), photo_ids=list(photo_ids), source_ids=list(dict.fromkeys(sids)),
                          issue_ids=[i['issue_id'] for i in issues], question=question, candidates=candidates))
    items.sort(key=lambda r: (r['priority'] != 'blocker', ORDER.get(r['rule_id'], 99), r['recommendation_id']))
    return dict(card_id=c['card_id'], provider_mode=c['provider_mode'], card_revision=c['revision'], generated_at=now(),
                readiness=deepcopy(c['readiness']), recommendations=items)
