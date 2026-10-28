import json
from pathlib import Path
from backend.ocr_text import parse_words, text_quality
from backend.inference import Providers, ROOT
from backend.version import API_VERSION

def tsv_word(text, conf=90, number=1, line=1):
    return f'5\t1\t1\t1\t{line}\t{number}\t10\t10\t30\t20\t{conf}\t{text}\n'

def test_quotes_are_literal_and_never_absorb_tsv_rows():
    data=tsv_word('"')+tsv_word('Состав:',number=2)+tsv_word('молоко',number=3)+tsv_word('"',number=4)
    words=parse_words(data,1000,1000)
    assert [w['text'] for w in words]==['"','Состав:','молоко','"']
    assert all('\t' not in w['text'] and '\n' not in w['text'] for w in words)

def test_symbol_noise_is_not_readable_even_with_large_native_scores():
    words=parse_words(''.join(tsv_word(s,conf=96,number=i+1) for i,s in enumerate(['=','|','3','4','“','Ё','==','\"'])),1000,1000)
    assert text_quality(words,1000,1000)=='unreadable'
    assert text_quality(parse_words(tsv_word('Сметана',conf=90),1000,1000),1000,1000)=='uncertain'
    label=''.join(tsv_word(t,number=i+1) for i,t in enumerate(['Творог','молочный','Состав:','молоко','закваска']))
    assert text_quality(parse_words(label,1000,1000),1000,1000)=='readable'

def test_malformed_rows_and_boxes_do_not_corrupt_sources():
    data='broken\trow\n'+tsv_word('word',conf=float('nan'))+tsv_word('zero',conf=0)+tsv_word('none',conf=-1)
    words=parse_words(data,1000,1000)
    assert [w['confidence'] for w in words]==[0,-1]
    assert all(0<=n<=1 for w in words for n in w['bbox'])

def test_no_text_photo_live_pipeline_does_not_generate_fields():
    # New generated blank image, not a substituted OCR response.
    import tempfile
    from PIL import Image
    with tempfile.TemporaryDirectory(dir=ROOT/'test-runtime') as folder:
        photo=Path(folder)/'blank.png';Image.new('RGB',(700,700),(130,150,140)).save(photo)
        provider=Providers()
        card=provider.analyze([{'photo_id':'blank','url':'/api/v1/photos/blank','width':700,'height':700,'quality':'uncertain'}],[photo],{},lambda _:None)
    assert all(f['value'] is None for f in card['fields'])
    assert card['category']['selected']=='unknown'
    assert card['photos'][0]['quality']=='unreadable'
    assert card['readiness']['required_filled']==0 and card['confirmation'] is None
