"""Crop retry is bounded, preserves geometry, and never fills fields itself."""
import json
from pathlib import Path
import subprocess
import tempfile
from PIL import Image
import pytest
from backend import ocr_refinement as refinement
from backend.domain import blank,source,score
from backend.inference import usable_primary
from backend.ocr_review import ocr_review


def test_refinement_maps_boxes_to_original_and_uses_real_word_scores(monkeypatch):
    root=Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(dir=root/'test-runtime') as folder:
        path=Path(folder)/'label.png';Image.new('RGB',(1000,1000),'white').save(path)
        monkeypatch.setenv('OCR_CACHE',folder)
        for lang in ('rus','eng'):(Path(folder)/f'{lang}.traineddata.gz').touch()
        def run(args,**kwargs):
            assert kwargs['timeout']==2 and kwargs['check']
            assert args[-1].endswith('title.png') and 'ocr.cjs' in args[-2]
            im=Image.open(args[-1]);w,h=im.size
            tsv=f'5\t1\t1\t1\t1\t1\t0\t0\t{w}\t{h}\t93\tExample product'
            return subprocess.CompletedProcess(args,0,stdout=json.dumps([{'tsv':tsv}]))
        monkeypatch.setattr(subprocess,'run',run)
        rows=refinement.refine_title(path,{'bbox':[.1,.1,.5,.2]},timeout=2)
        assert rows[0]['bbox']==[.097,.097,.503,.203]
        assert rows[0]['confidence']==pytest.approx(.93)
        assert rows[0]['words'][0]['confidence']==93
        card=blank([])
        source(card,rows[0]['text'],'ocr_text',score(.93,'ocr_aggregate',refinement.PROVIDER),'p',rows[0]['bbox'])
        assert ocr_review(card)['counts']['useful']==1
        assert all(f['value'] is None for f in card['fields'])


def test_missing_crop_models_do_not_download_or_break_primary_result(monkeypatch):
    root=Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(dir=root/'test-runtime') as folder:
        monkeypatch.setenv('OCR_CACHE',folder)
        def forbidden(*args,**kwargs):raise AssertionError('No process or network without crop weights')
        monkeypatch.setattr(subprocess,'run',forbidden)
        assert refinement.refine_title(Path(folder)/'absent.png',{'bbox':[0,0,1,1]})==[]
        assert refinement.refine_title(Path(folder)/'absent.png',{'bbox':[0,0,1,1]},timeout=0)==[]


def test_no_retry_if_primary_contains_a_valid_property_or_title():
    assert usable_primary(dict(text='Brand: Example',confidence=.95,words=[],bbox=[0,.3,1,.4]))
    assert usable_primary(dict(text='Example product name',confidence=.95,words=[],bbox=[0,.05,1,.1]))
    assert not usable_primary(dict(text='Brаnd: Mиlк',confidence=.99,words=[],bbox=[0,.05,1,.1]))
