"""Noisy label triage is reversible and never turns guesses into facts."""
import copy
import json
import jsonschema
import pytest
from PIL import Image
from backend import main
from backend.domain import blank,source,score
from backend.ocr_review import assess_line,ocr_review
from backend.ocr_input import prepare_inputs
from test_presentation import client,seed

@pytest.mark.parametrize('text',['amt','i','eit','Cl','5','—','fl','ET pe ST','3: (ch) 1941','apa cuca. 8 Occ'])
def test_isolated_fragments_stay_out_of_useful_text(text):
    assert assess_line(text,.95)[0]!='useful'

@pytest.mark.parametrize('text',['3M','C-20','XL','20 W','330ml','USB'])
def test_short_models_and_units_are_preserved_for_manual_review(text):
    # USB is an acronym, not a full property; it can remain in doubtful raw text.
    if text=='330ml': assert assess_line(text,.95)==('useful','field','net_quantity')
    else: assert assess_line(text,.95)[0] in ('other','doubtful')
    c=blank([]);source(c,text,'ocr_text',score(.95,'ocr_aggregate','fixture'))
    assert ocr_review(c)['lines'][0]['text']==text

def test_low_score_heading_cannot_be_auto_filled_and_mixed_script_is_suspect():
    assert assess_line('Brand: Mиlк',.99)[0]=='doubtful'
    assert assess_line('Model: X-12',.1)[0]=='doubtful'
    assert assess_line('Brand: 3M',.95)==('useful','field','brand')

def test_weak_punctuation_does_not_hide_legible_property_but_weak_value_does():
    words=[{'text':'Brand:','confidence':95},{'text':'Example','confidence':95},{'text':'®','confidence':0}]
    assert assess_line('Brand: Example ®',0,words)[0]=='useful'
    words[1]['confidence']=10
    assert assess_line('Brand: Example ®',0,words)[0]=='doubtful'
    assert assess_line('Manufacturer: AB',.9,[dict(text='Manufacturer:',confidence=96),dict(text='AB',confidence=0)])[0]=='doubtful'

def test_dedup_preserves_all_observations_and_suspicious_dates_stay_hidden():
    c=blank([dict(photo_id='p',url='',width=356,height=356,quality='readable')])
    for text,conf in [('Brand: Example',.9),('Brand: Example',.9),('i',.99),('Lot 1941 =',.1)]:
        source(c,text,'ocr_text',score(conf,'ocr_aggregate','fixture'),'p',[0,.2,.9,.3])
    before=copy.deepcopy(c);review=ocr_review(c)
    assert c==before
    assert review['counts']==dict(raw=4,useful=1,other=0,doubtful=2,duplicates=1)
    row=review['lines'][0]
    assert len(row['source_ids'])==2 and row['suggested_value']=='Example'
    assert review['warnings'] and '356×356' in review['warnings'][0]
    assert all(f['value'] is None for f in c['fields'])

def test_top_line_candidate_never_promotes_body_text_into_a_name():
    c=blank([])
    source(c,'Useful instruction on packaging','ocr_text',score(.95,'ocr_aggregate','fixture'),'p',[0,.25,.9,.3])
    assert ocr_review(c)['counts']['useful']==0

def test_explicit_product_name_suppresses_a_second_geometric_title():
    c=blank([])
    source(c,'Product: Sample notebook','ocr_text',score(.99,'ocr_aggregate','fixture'),'p',[0,.01,.9,.04])
    source(c,'Keep the packaging for reference','ocr_text',score(.99,'ocr_aggregate','fixture'),'p',[0,.08,.9,.11])
    rows=ocr_review(c)['lines']
    assert rows[0]['field_id']=='product_name' and rows[0]['group']=='useful'
    assert rows[1]['group']=='other'


def test_value_formats_and_top_title_threshold_reject_noise():
    assert assess_line('Quantity: water sugar',.99)[0]=='doubtful'
    assert assess_line('Best before: see bottom',.99)[0]!='useful'
    assert assess_line('Brand: Mølk',.99)[0]=='doubtful'
    c=blank([])
    source(c,'Unreadable product fragment','ocr_text',score(.84,'ocr_aggregate','fixture'),'p',[0,.02,.9,.12])
    source(c,'www.example.com','ocr_text',score(.99,'ocr_aggregate','fixture'),'p',[0,.02,.9,.12])
    assert ocr_review(c)['counts']['useful']==0

@pytest.fixture
def working_path():
    import tempfile
    with tempfile.TemporaryDirectory(dir=main.ROOT/'test-runtime') as folder:
        from pathlib import Path
        yield Path(folder)

def test_working_copy_upscale_leaves_original_and_dimensions_unchanged(working_path):
    tmp_path=working_path
    original=tmp_path/'original.png';Image.new('RGB',(356,356),'red').save(original)
    before=original.read_bytes();folder=tmp_path/'working';folder.mkdir()
    files,sizes=prepare_inputs([original],folder)
    assert original.read_bytes()==before and Image.open(original).size==(356,356)
    assert sizes==[(1068,1068)] and files[0]!=original
    # Normalized coordinates still map to the same spot on the original image.
    from backend.ocr_text import parse_words
    tsv='5\t1\t1\t1\t1\t1\t267\t267\t534\t534\t95\tExample'
    assert parse_words(tsv,*sizes[0])[0]['bbox']==[.25,.25,.75,.75]

def test_review_api_is_private_revision_guarded_schema_valid_and_read_only(client):
    c,owner=seed(client);path='/api/v1/cards/'+c['card_id']
    before=client.get(path).json()
    r=client.get(path+'/ocr-review',params={'expected_revision':c['revision']})
    assert r.status_code==200,r.text
    main.validate('OCRReview',r.json())
    assert client.get(path).json()==before
    assert client.get(path+'/ocr-review',params={'expected_revision':c['revision']+1}).status_code==409
    from fastapi.testclient import TestClient
    with TestClient(main.app) as stranger:
        assert stranger.get(path+'/ocr-review',params={'expected_revision':c['revision']}).status_code==404
    assert client.get(path+'/ocr-review').status_code==422
