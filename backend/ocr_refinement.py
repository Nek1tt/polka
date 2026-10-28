"""One bounded re-read of a detected title region, never of the whole photo.

The CPU comparison found a regression on a real small title ROI. Re-use its
geometry and the measured stronger recognizer there; scores are not compared
across models. The result is a manual candidate, not an accepted product fact.
"""
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from PIL import Image
from .ocr_text import parse_words

ROOT=Path(__file__).resolve().parents[1]
PROVIDER='Tesseract.js 6.0.1 rus+eng / detected title crop / character-weighted word score'


def refine_title(path,line,timeout=15):
    # No network fallback if historical benchmark models are absent.
    cache=Path(os.getenv('OCR_CACHE',str(ROOT/'model-cache')))
    if timeout<=0 or not all((cache/f'{lang}.traineddata.gz').is_file() for lang in ('rus','eng')):
        return []
    with tempfile.TemporaryDirectory(prefix='title-',dir=path.parent) as folder:
        with Image.open(path) as image:
            b=line['bbox'];pad=3
            rect=(max(0,int(b[0]*image.width)-pad),max(0,int(b[1]*image.height)-pad),
                  min(image.width,int(b[2]*image.width)+pad),min(image.height,int(b[3]*image.height)+pad))
            crop=image.crop(rect)
            factor=min(3,1200/max(crop.size));size=(round(crop.width*factor),round(crop.height*factor))
            target=Path(folder)/'title.png';crop.resize(size,Image.Resampling.BICUBIC).save(target)
            image_size=image.size
        try:
            process=subprocess.run([os.getenv('NODE_BINARY','node'),str(ROOT/'ocr.cjs'),str(target)],cwd=ROOT,
                                   capture_output=True,text=True,encoding='utf-8',check=True,timeout=timeout)
            words=parse_words(json.loads(process.stdout)[0]['tsv'],*size)
        except (OSError,subprocess.SubprocessError,ValueError,KeyError):
            return []
    groups={}
    for word in words:
        box=word['bbox']
        word['bbox']=[(rect[0]+box[0]*(rect[2]-rect[0]))/image_size[0],
                      (rect[1]+box[1]*(rect[3]-rect[1]))/image_size[1],
                      (rect[0]+box[2]*(rect[2]-rect[0]))/image_size[0],
                      (rect[1]+box[3]*(rect[3]-rect[1]))/image_size[1]]
        groups.setdefault(word['group'],[]).append(word)
    lines=[]
    for rows in groups.values():
        weights=[len(re.findall(r'[A-Za-zА-Яа-яЁё]',w['text'])) for w in rows]
        confidence=sum(max(0,w['confidence'])*n for w,n in zip(rows,weights))/max(1,sum(weights))/100
        boxes=[w['bbox'] for w in rows]
        lines.append(dict(text=' '.join(w['text'] for w in rows),confidence=confidence,words=rows,provider=PROVIDER,
                          bbox=[min(b[0] for b in boxes),min(b[1] for b in boxes),max(b[2] for b in boxes),max(b[3] for b in boxes)]))
    return lines
