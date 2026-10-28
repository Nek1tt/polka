"""Reproducible CPU comparison. Synthetic smoke is NOT a product accuracy benchmark.

Optional private manifest: [{id, path, text, crop?: [x0,y0,x1,y1]}].
The report stores metrics only; private photographs/transcripts stay outside releases.
"""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import threading
import time
import psutil
from PIL import Image, ImageEnhance

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.local_ocr import create_engine, recognize
from backend.ocr_input import prepare_inputs
from backend.ocr_text import parse_words


def norm(text):
    return ' '.join(re.findall(r'[\w]+', text.casefold().replace('ё', 'е')))


def distance(a, b):
    row = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        following = [i]
        for j, y in enumerate(b, 1):
            following.append(min(following[-1] + 1, row[j] + 1, row[j-1] + (x != y)))
        row = following
    return row[-1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--manifest', type=Path)
    parser.add_argument('--output', type=Path, default=ROOT/'docs/ocr-cpu-comparison.json')
    parser.add_argument('--easyocr',action='store_true',help='Optional comparison dependency; not installed in the product requirements')
    parser.add_argument('--download-easyocr-models',action='store_true',help='Explicit benchmark model download; no photographs leave this machine')
    args = parser.parse_args()
    cases = [
        dict(id='ru-clean', path=str(ROOT/'data/demo/dairy.png'), text='Название: Творог молочный Масса нетто: 250 г Состав: молоко, закваска Хранение: от +2 до +6 C Срок годности: 7 суток Производитель: Учебный пример СИНТЕТИЧЕСКАЯ ТЕСТОВАЯ ЭТИКЕТКА'),
        dict(id='en-clean', path=str(ROOT/'data/demo/cable.png'), text='Product: USB cable Brand: Example Model: C-20 Material: Nylon Color: Black Specifications: Length 2 m СИНТЕТИЧЕСКАЯ ТЕСТОВАЯ ЭТИКЕТКА'),
    ]
    if args.manifest:
        cases += [{**c, 'real': True} for c in json.loads(args.manifest.read_text(encoding='utf-8'))]
    reports = []
    with tempfile.TemporaryDirectory(dir=ROOT/'test-runtime') as folder:
        folder = Path(folder)
        prepared_cases = []
        for case in cases:
            im = Image.open(case['path']).convert('RGB')
            if case.get('crop'):
                im = im.crop(case['crop'])
            versions = [('original', im)] if case.get('real') else [('original', im), ('tilt', im.rotate(8, expand=True, fillcolor='white')), ('lowcontrast', ImageEnhance.Contrast(im).enhance(.35)), ('small', im.resize((550,310)))]
            for kind, image in versions:
                path = folder/f'{len(prepared_cases)}.png';image.save(path)
                copies, sizes = prepare_inputs([path], folder/f'working-{len(prepared_cases)}')
                prepared_cases.append((case, kind, copies[0], sizes[0]))
        models=['Tesseract.js rus+eng PSM3/11', 'PP-OCRv5 mobile eslav ONNX CPU']
        if args.easyocr:models.append('EasyOCR 1.7.2 Cyrillic+English CPU')
        for model in models:
            peak = [0];stop = threading.Event()
            def sample():
                while not stop.wait(.02):
                    proc = psutil.Process()
                    rss = proc.memory_info().rss
                    for child in proc.children(recursive=True):
                        try: rss += child.memory_info().rss
                        except psutil.Error: pass
                    peak[0] = max(peak[0], rss)
            sampler = threading.Thread(target=sample, daemon=True);sampler.start()
            try:
                startup = time.perf_counter()
                engine = create_engine() if model.startswith('PP') else None
                if model.startswith('Easy'):
                    import easyocr
                    import torch
                    torch.set_num_threads(4)
                    engine=easyocr.Reader(['ru','en'],gpu=False,verbose=False,model_storage_directory=str(ROOT/'model-cache/easyocr'),user_network_directory=str(ROOT/'model-cache/easyocr/user_network'),download_enabled=args.download_easyocr_models)
                load_seconds = time.perf_counter()-startup
                for case, kind, path, size in prepared_cases:
                    started = time.perf_counter()
                    if model.startswith('Easy'):
                        predicted=' '.join(row[1] for row in engine.readtext(str(path),workers=0))
                    elif engine:
                        lines = recognize(engine, path);predicted = ' '.join(l['text'] for l in lines)
                    else:
                        result = subprocess.run([os.getenv('NODE_BINARY','node'),str(ROOT/'ocr.cjs'),str(path)],check=True,capture_output=True,text=True,encoding='utf-8',timeout=90)
                        predicted = ' '.join(w['text'] for w in parse_words(json.loads(result.stdout)[0]['tsv'],*size))
                    reference, predicted = norm(case['text']), norm(predicted)
                    reports.append(dict(model=model,id=case['id'],variant=kind,dataset='real ROI' if case.get('real') else 'synthetic',
                                        seconds=round(time.perf_counter()-started,3),cer=round(distance(reference,predicted)/max(1,len(reference)),4),
                                        wer=round(distance(reference.split(),predicted.split())/max(1,len(reference.split())),4),
                                        reference_characters=len(reference),load_seconds=round(load_seconds,3)))
            finally:
                stop.set();sampler.join()
            for r in reports:
                if r['model']==model:r['sampled_process_tree_peak_mib']=round(peak[0]/1024**2,1)
    data=dict(hardware=dict(cpu=__import__('platform').processor(),logical_cpus=os.cpu_count(),threads={'PP-OCRv5':4,'EasyOCR':4,'Tesseract':'existing default worker'},device='CPU'),
              limitations='Small engineering comparison, not a held-out accuracy estimate. Real ROIs may share one photograph. Tesseract time includes its existing per-job worker initialization; PP-OCR startup listed separately. Peak is sampled process tree including benchmark harness. No cloud calls.',cases=reports)
    args.output.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(data,ensure_ascii=True))


if __name__=='__main__':main()
