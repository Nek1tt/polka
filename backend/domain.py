import copy
import re
import uuid
from datetime import datetime, timezone

LABELS = {'product_name':'Название товара','net_quantity':'Масса, объём или количество','brand':'Бренд','model':'Модель / артикул','material':'Материал','dimensions':'Размеры','color':'Цвет','specifications':'Другие характеристики','manufacturer':'Производитель','ingredients':'Состав','storage_conditions':'Условия хранения','shelf_life':'Срок годности','fat_percent':'Жирность'}
# A universal prototype cannot prescribe marketplace requirements for every product.
# The seller can mark any additional characteristic required for this draft.
REQUIRED = ['product_name']
def now(): return datetime.now(timezone.utc).isoformat()
def uid(): return uuid.uuid4().hex
def score(value, kind, provider): return dict(value=float(value),kind=kind,provider=provider,calibrated=False)
def source(card, text, kind='user_input', confidence=None, photo_id=None, bbox=None, inputs=None):
    s=dict(source_id=uid(),kind=kind,text=text,photo_id=photo_id,bbox=bbox,confidence=confidence,input_source_ids=inputs or [],created_at=now())
    card['sources'].append(s)
    return s['source_id']
def normalized(v): return re.sub(r'\s+', ' ', (v or '').strip()).casefold().replace('ё','е')
def field_label(field): return field.get('label') or LABELS.get(field['field_id'], field['field_id'])
def name_requirement(card):
    """Only the product name is required, including historical cards."""
    changed=False
    for field in card['fields']:
        required=field['field_id']=='product_name'
        changed=changed or field['required']!=required
        field['required']=required
    return changed
def template(card):
    statements=[]
    for f in card['fields']:
        if f['value'] and f['reviewed'] and f['status']=='accepted':
            statements.append(dict(text=f"{field_label(f)}: {f['value']}",source_ids=f['source_ids'][:],asserted_as_user_input=False))
    return dict(text='\n'.join(s['text'] for s in statements),mode='template',source_ids=list(dict.fromkeys(x for s in statements for x in s['source_ids'])),reviewed=False,statements=statements)
def blank(photos):
    c=dict(schema_version='2.2',card_id=uid(),revision=1,created_at=now(),expires_at='',provider_mode='live',ruleset_version='2.3.0',ocr=dict(mode='local',provider='Not processed',languages=['ru','en']),photos=photos,sources=[],category=dict(selected='unknown',suggested='unknown',reviewed=False,source_ids=[],scores=[],method='Explicit text headings; no category model',model_version='rules-2'),fields=[],description={},issues=[],readiness={},confirmation=None)
    for key in LABELS:
        c['fields'].append(dict(field_id=key,value=None,required=key in REQUIRED,status='missing',reviewed=False,source_ids=[],confidence=None,candidates=[]))
    c['description']=template(c)
    return c
def add_candidate(c,f,value,sid,confidence=None,user=False):
    if not value or not value.strip(): return
    value=value.strip()
    f['candidates'].append(dict(value=value,source_ids=[sid],confidence=confidence))
    previous=f['value']
    conflict=f['status']=='conflict' or (previous is not None and normalized(previous)!=normalized(value))
    if previous is None or user:
        f.update(value=value,source_ids=[sid],confidence=confidence,reviewed=user)
    f['status']='conflict' if conflict else ('accepted' if f['reviewed'] else 'suggested')
def moderate(c):
    name_requirement(c)
    issues=[]; missing=[]; review=[]
    def issue(rule,msg,suggestion,field=None,severity='blocker',photos=None):
        issues.append(dict(issue_id=rule+':'+(field or 'card'),rule_id=rule,severity=severity,message=msg,suggestion=suggestion,field_ids=[field] if field else [],photo_ids=photos or []))
    for f in c['fields']:
        key=f['field_id']; label=field_label(f)
        if not f['value']:
            if f['required']:
                missing.append(key); issue('missing_required',f'Не заполнено: {label}','Укажите сведения с упаковки или из собственных данных',key)
        else:
            if f['status']=='conflict': issue('unresolved_conflict',f'Противоречие: {label}','Сравните источники и явно разрешите противоречие',key)
            if not f['reviewed']:
                review.append(key); issue('unreviewed_value',f'Проверьте: {label}','Сравните значение с этикеткой и нажмите «Проверено»',key)
            conf=f['confidence']
            if conf and conf['value'] < (85 if conf['kind']=='ocr_native_0_100' else .85): issue('low_ocr_score',f'Низкая оценка OCR: {label}','Сверьте с фото или исправьте вручную',key,'warning')
    cat=c['category']
    if cat['selected']!='unknown' and not cat['reviewed']:
        review.append('category');issue('unreviewed_value','Проверьте категорию','Подтвердите или исправьте категорию','category')
    if not c['description']['reviewed'] or not c['description']['text']:
        review.append('description');issue('description_needs_review','Описание требует проверки','Сформируйте текст из принятых полей или подтвердите происхождение своего текста','description')
    # Deterministic checks only: quantity and explicit field-labelled lines.
    desc=c['description']; fields={f['field_id']:f for f in c['fields']}
    quantities=re.findall(r'\b\d+(?:[.,]\d+)?\s*(?:кг|мл|л|г|kg|ml|g|l)\b',desc['text'],re.I) if desc['mode']!='template' else []
    selected=fields.get('net_quantity',{}).get('value')
    if selected and any(normalized(q).replace(' ','')!=normalized(selected).replace(' ','') for q in quantities):
        issue('unresolved_conflict','Количество в описании расходится с характеристикой','Исправьте количество в описании','description')
    for line in desc['text'].splitlines():
        for key,field in fields.items():
            label=field_label(field)
            if line.startswith(label+':') and normalized(line.split(':',1)[1])!=normalized(fields[key]['value']):
                issue('unresolved_conflict',f'Описание расходится с полем «{label}»','Исправьте описание или характеристику','description')
    ingredients=normalized(fields.get('ingredients',{}).get('value'))
    for claim,ingredient in [('без сахара','сахар'),('без соли','соль')]:
        if claim in normalized(desc['text']) and re.search(r'\b'+ingredient+r'\b',ingredients):
            issue('unresolved_conflict',f'Утверждение «{claim}» противоречит составу','Исправьте описание или уточните состав','description')
    if not c['photos']: issue('missing_photos','Добавьте фотографии товара','Карточку можно заполнить вручную. Фото понадобятся для оформления и OCR-подсказок.',severity='warning')
    if c['photos'] and all(p['quality']=='unreadable' for p in c['photos']): issue('unreadable_photos','OCR не нашёл надёжного текста','Добавьте крупный снимок надписи или заполните сведения вручную. Товар без надписей тоже допустим.',severity='warning')
    for p in c['photos']:
        if p['quality']=='uncertain': issue('poor_photo','OCR-текст требует проверки','Сравните текст с фотографией. При необходимости снимите надпись ближе, без бликов.',severity='warning',photos=[p['photo_id']])
        if min(p['width'],p['height'])<600 and sum(1 for s in c['sources'] if s['kind']=='ocr_text' and s['photo_id']==p['photo_id'] and s.get('confidence') and s['confidence']['kind']=='ocr_aggregate')>=10:
            issue('low_resolution','Слишком мелкий текст для надёжного OCR',f"Фото {p['width']}×{p['height']}. Загрузите исходник или крупный фрагмент нужной надписи; увеличение не восстановит детали.",severity='warning',photos=[p['photo_id']])
    if not any(f['value'] for f in c['fields'] if f['field_id']!='product_name'):
        issue('optional_missing','Добавьте известные характеристики','Выберите подходящие поля: бренд, модель, материал, размеры или другие характеристики. Не заполняйте неизвестное.',severity='warning')
    # IDs must remain unique even if multiple rules refer to description/photos.
    for i,x in enumerate(issues): x['issue_id']+=f':{i}'
    blockers=[x['issue_id'] for x in issues if x['severity']=='blocker']
    state='needs_information' if missing else 'needs_review' if blockers else 'confirmed' if c['confirmation'] and c['confirmation']['confirmed_revision']==c['revision'] else 'ready_to_confirm'
    c['issues']=issues
    total=sum(f['required'] for f in c['fields'])
    c['readiness']=dict(state=state,required_filled=total-len(missing),required_total=total,missing_fields=missing,review_fields=list(dict.fromkeys(review)),blocking_issue_ids=blockers)
    return c
def patch(c,p):
    c=copy.deepcopy(c); changed_fields=False
    from .attributes import change_fields, CATALOG, new_field
    if p.get('add_fields') or p.get('remove_fields'):
        change_fields(c,p); changed_fields=True
    fields={f['field_id']:f for f in c['fields']}
    for update in p.get('field_updates',[]):
        key=update['field_id']
        if key not in fields:
            if key not in CATALOG or len(fields)>=80:
                raise ValueError('Сначала добавьте характеристику в карточку')
            fields[key]=new_field(key);c['fields'].append(fields[key]);changed_fields=True
    for u in p.get('field_updates',[]):
        f=fields[u['field_id']]; value=(u['value'] or '').strip() or None
        if not f.get('label') and (value or f['value'] or u.get('required',f['required'])):
            f['label']=field_label(f)
        required=f['field_id']=='product_name'
        if required!=f['required']: changed_fields=True
        f['required']=required
        if value!=f['value'] or u.get('resolve_conflict'):
            changed_fields=True
            if value:
                sid=source(c,value); f['candidates'].append(dict(value=value,source_ids=[sid],confidence=None))
                f.update(value=value,source_ids=[sid],confidence=None)
            else: f.update(value=None,source_ids=[],confidence=None)
        if f['reviewed']!=u['reviewed']: changed_fields=True
        conflict=f['status']=='conflict' and not u.get('resolve_conflict',False)
        f['reviewed']=u['reviewed'] and value is not None and not conflict
        f['status']='conflict' if conflict else 'missing' if value is None else 'accepted' if f['reviewed'] else 'suggested'
    if p.get('category_update'):
        u={**p['category_update'],'selected':p['category_update']['selected'].strip() or 'unknown'}; cat=c['category']
        if cat['selected']!=u['selected'] or cat['reviewed']!=u['reviewed']:
            sid=source(c,u['selected']);cat.update(selected=u['selected'],reviewed=u['reviewed'],source_ids=[sid]);changed_fields=True
    if changed_fields:
        if c['description']['mode']=='template': c['description']=template(c)
        else: c['description']['reviewed']=False
    if p.get('description_update'):
        d=p['description_update']; generated=template(c)
        if d['text']==c['description']['text'] and c['description']['mode']=='llm':
            c['description']['reviewed']=d['reviewed']
        elif d['text']==generated['text']:
            c['description']=generated;c['description']['reviewed']=d['reviewed']
        else:
            sid=source(c,d['text'])
            c['description']=dict(text=d['text'],mode='user',source_ids=[sid],reviewed=d['reviewed'] and d['asserted_as_user_input'],statements=[dict(text=d['text'],source_ids=[sid],asserted_as_user_input=d['asserted_as_user_input'])] if d['text'] else [])
    c['revision']+=1;c['confirmation']=None
    return moderate(c)
