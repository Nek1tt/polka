"""Read-only OCR triage. Heuristics select observations, never rewrite facts."""
import re
from collections import Counter
from .domain import normalized
from .extraction import classify_line

LETTERS=re.compile(r'[A-Za-zА-Яа-яЁё]')
REASONS={
 'fragment':'Короткий обрывок или отдельный символ',
 'mixed_script':'Смешаны русские и английские буквы внутри слова',
 'low_score':'Низкие оценки OCR или много неразборчивых символов',
 'field':'Явный заголовок характеристики; значение нужно проверить',
 'title':'Возможно, название: строка вверху фото; отдельные слова могут быть ошибочны',
 'other':'Прочий текст: не назначен характеристике автоматически',
 'linked':'Строка уже используется как источник характеристики',
 'non_content':'Служебная надпись, адрес, ссылка или телефон',
 'unsupported':'Есть символы вне русского и английского алфавита',
 'invalid_value':'Значение не соответствует формату характеристики',
}

def mixed_script(text):
    return any(re.search('[A-Za-z]',t) and re.search('[А-Яа-яЁё]',t) for t in re.findall(r'[\w-]+',text))

def is_technical(text):
    # Preserve short, legitimate model/size/unit tokens in the secondary section.
    return bool(re.fullmatch(r'(?:[A-Za-z]{1,5}[- ]?\d[\w.-]{0,18}|\d+(?:[.,]\d+)?\s*(?:мл|л|кг|г|шт|мм|см|м|ml|l|kg|g|pcs|mm|cm|m|W|V)|[XSML]{1,4})',text,re.I))

def assess_line(text,confidence=None,words=None):
    letters=len(LETTERS.findall(text)); key,value=classify_line(text)
    if any(c.isalpha() and not LETTERS.fullmatch(c) for c in text): return 'doubtful','unsupported',key
    if mixed_script(text): return 'doubtful','mixed_script',key
    if key=='net_quantity' and not re.fullmatch(r'\d+(?:[.,]\d+)?\s*(?:кг|г|мл|л|шт\.?|kg|g|ml|l|pcs)',value,re.I):
        return 'doubtful','invalid_value',key
    if key=='shelf_life' and (re.search(r'см\.?|смотри|see|bottom|дне|крышк',value,re.I) or not re.search(r'\d',value)):
        return 'other','invalid_value',key
    if letters<4 and not (is_technical(text) or key): return 'doubtful','fragment',key
    if not key and letters/max(1,len(text))<.45 and not is_technical(text): return 'doubtful','low_score',None
    # Use actual word observations when available. A punctuation mark with a low
    # native score must not hide a whole otherwise legible line.
    if words:
        weights=[(max(1,len(LETTERS.findall(w['text']))),w['confidence']) for w in words]
        total=sum(w for w,_ in weights)
        reliable=sum(w for w,score in weights if score>=60)/total
        clean=sum(w for w,score in weights if score>=35)/total
        legible=reliable>=.60 and clean>=.85
    else: legible=confidence is not None and confidence>=.85
    if not legible: return 'doubtful','low_score',key
    if not key and (re.search(r'https?://|www\.|[\w.-]+@[\w.-]+|\b(?:ул\.|улица|street|тел\.|телефон)\b',text,re.I) or re.fullmatch(r'[+()\d\s.-]{7,}',text)):
        return 'other','non_content',None
    if key and words:
        # A long reliable heading must not mask a garbled short value.
        value_words=words[-len(value.split()):]
        weight=sum(max(1,len(LETTERS.findall(w['text']))) for w in value_words)
        clean=sum(max(1,len(LETTERS.findall(w['text']))) for w in value_words if w['confidence']>=35)
        if clean/max(1,weight)<.85: return 'doubtful','low_score',key
    if key: return 'useful','field',key
    return 'other','other',None

def word_evidence(line,sources):
    refs=set(line.get('input_source_ids',[]))
    if refs:
        return [dict(text=s['text'],confidence=s['confidence']['value']) for s in sources
                if s['source_id'] in refs and s.get('confidence') and s['confidence']['kind']=='ocr_native_0_100']
    # v2.0 cards predate explicit word linkage; geometry remains immutable.
    box=line.get('bbox')
    if not box: return []
    return [dict(text=s['text'],confidence=s['confidence']['value']) for s in sources
            if s['kind']=='ocr_text' and s['photo_id']==line['photo_id'] and s.get('bbox') and s.get('confidence') and
            s['confidence']['kind']=='ocr_native_0_100' and
            s['bbox'][0]>=box[0]-1e-6 and s['bbox'][1]>=box[1]-1e-6 and s['bbox'][2]<=box[2]+1e-6 and s['bbox'][3]<=box[3]+1e-6]

def ocr_review(card):
    lines=[s for s in card['sources'] if s['kind']=='ocr_text' and s.get('confidence') and s['confidence']['kind']=='ocr_aggregate']
    linked={sid:f['field_id'] for f in card['fields'] for sid in f['source_ids']}
    explicit_titles={line['photo_id'] for line in lines if classify_line(line['text'])[0]=='product_name'
                     and assess_line(line['text'],line['confidence']['value'],word_evidence(line,card['sources']))[0]=='useful'}
    rows=[];dedup={};duplicates=0;photo_titles=Counter()
    for line in lines:
        conf=line['confidence'];words=word_evidence(line,card['sources'])
        group,reason,key=assess_line(line['text'],conf['value'],words)
        if group!='doubtful' and line['source_id'] in linked:
            group,reason,key='useful','linked',linked[line['source_id']]
        elif line['photo_id'] not in explicit_titles and not key and reason=='other' and group=='other' and conf['value']>=.90 and line.get('bbox') and line['bbox'][1]<.16 and len(LETTERS.findall(line['text']))>=12 and len(line['text'].split())>=2 and photo_titles[line['photo_id']]<1:
            group,reason,key='useful','title',None;photo_titles[line['photo_id']]+=1
        identity=(normalized(line['text']),group,key)
        if identity in dedup:
            dedup[identity]['source_ids'].append(line['source_id']);duplicates+=1;continue
        _,value=classify_line(line['text'])
        row=dict(text=line['text'],source_ids=[line['source_id']],photo_id=line['photo_id'],bbox=line['bbox'],confidence=conf,
                 group=group,reason=REASONS[reason],field_id=key,suggested_value=value)
        rows.append(row);dedup[identity]=row
    warnings=[]
    for p in card['photos']:
        if min(p['width'],p['height'])<600:
            warnings.append(f"Фото {p['width']}×{p['height']}: мелкие надписи могут теряться. Используйте исходник или отдельный крупный снимок текста. Увеличение не восстанавливает утраченные детали.")
    counts=Counter(row['group'] for row in rows)
    return dict(card_id=card['card_id'],card_revision=card['revision'],filter_version='ocr-triage-2',
                counts=dict(raw=len(lines),useful=counts['useful'],other=counts['other'],doubtful=counts['doubtful'],duplicates=duplicates),
                warnings=warnings,lines=rows,
                notice='Отбор по правилам и оценкам OCR, не проверка фактов. Исходные наблюдения сохранены; текст не исправляется догадками.')
