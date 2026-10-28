"""Local RU/EN OCR and explicit, auditable if/else field classification."""
import json
import os
import re
import subprocess
import sys
import time
import tempfile
from pathlib import Path
from .domain import source,score,add_candidate,moderate,template,blank
from .ocr_text import text_quality
from .ocr_input import prepare_inputs
from .ocr_review import assess_line
from .ocr_refinement import refine_title,PROVIDER as REFINEMENT_PROVIDER
from . import cloud_ocr
from .local_ocr import PROVIDER as LOCAL_PROVIDER
ROOT=Path(__file__).resolve().parents[1]
from .extraction import HEADINGS,classify_line

def usable_primary(line):
    group,reason,_=assess_line(line['text'],line['confidence'],line['words'])
    return group=='useful' or (group=='other' and reason=='other' and line['confidence']>=.90 and
                             line['bbox'][1]<.16 and len(re.findall(r'[A-Za-zА-Яа-яЁё]',line['text']))>=12 and len(line['text'].split())>=2)

class Providers:
    def __init__(self): self.ready=False;self.reason='OCR не проверен'
    def check(self):
        try:
            subprocess.run([sys.executable,'-m','backend.ocr_runner','--check'],cwd=ROOT,check=True,timeout=45,capture_output=True)
            self.ready=True;self.reason=LOCAL_PROVIDER
        except (OSError,subprocess.SubprocessError): self.ready=False;self.reason='Локальная модель недоступна: установите requirements.txt и выполните scripts/download_local_models.py'
    def available(self,mode):
        return self.ready if mode=='local' else cloud_ocr.configured() if mode=='api' else False
    def modes(self):
        return [dict(id='local',label='Локальная модель',provider=LOCAL_PROVIDER,available=self.ready,sends_photos=False,
                     notice='Работает на процессоре этого сервера. Фотографии не передаются внешним сервисам.' if self.ready else 'Локальная модель пока не установлена на сервере.'),dict(id='api',label='Через API',provider=cloud_ocr.PROVIDER,available=cloud_ocr.configured(),sends_photos=True,
                     notice='Фото будет передано Google Cloud Vision. Возможна плата за запросы.' if cloud_ocr.configured() else 'Google Cloud Vision пока не подключён на сервере. Фотографии не отправляются.')]
    @staticmethod
    def extract(c,text,sid,conf):
        key,value=classify_line(text)
        if key:
            if key=='shelf_life' and re.search(r'см\.?|смотри|see|bottom|дне|крышк',value,re.I): return
            add_candidate(c,next(f for f in c['fields'] if f['field_id']==key),value,sid,conf)
    def analyze(self,photos,paths,initial,stage):
        c=blank(photos);stage('ocr');mode=initial.get('ocr_mode','local');deadline=time.monotonic()+int(os.getenv('OCR_TIMEOUT','90'))
        provider=LOCAL_PROVIDER if mode=='local' else cloud_ocr.PROVIDER
        c['ocr']=dict(mode=mode,provider=provider,languages=['ru','en'])
        with tempfile.TemporaryDirectory(prefix='ocr-',dir=paths[0].parent) as folder:
            prepared,sizes=prepare_inputs(paths,folder)
            if mode=='local':
                result=subprocess.run([sys.executable,'-m','backend.ocr_runner',*map(str,prepared)],cwd=ROOT,check=True,capture_output=True,text=True,encoding='utf-8',timeout=int(os.getenv('OCR_TIMEOUT','90')))
                outputs=json.loads(result.stdout)
            elif mode=='api': outputs=[cloud_ocr.recognize(path) for path in prepared]
            else: raise ValueError('INVALID_OCR_MODE')
        for photo,output,size,path in zip(photos,outputs,sizes,paths):
            # At most one detected title region per photo, only when PP found
            # no reliable field/title candidate. Do not compare model scores.
            if mode=='local' and not any(usable_primary(l) for l in output):
                regions=[l for l in output if l['bbox'][1]<.16 and len(re.findall(r'[A-Za-zА-Яа-яЁё]',l['text']))>=12 and l['confidence']>=.70]
                if regions:
                    refined=refine_title(path,min(regions,key=lambda l:l['bbox'][1]),timeout=min(15,deadline-time.monotonic()))
                    if refined:
                        output=output+refined;c['ocr']['provider']=LOCAL_PROVIDER+' + '+REFINEMENT_PROVIDER
            words=[dict(text=l['text'],confidence=l['confidence']*100) for l in output]
            photo['quality']=text_quality(words,photo['width'],photo['height'])
            for line in output:
                text=line['text'];rows=line['words'];line_provider=line.get('provider',provider);conf=score(line['confidence'],'ocr_aggregate',line_provider)
                bbox=line['bbox']
                sid=source(c,text,'ocr_text',conf,photo['photo_id'],bbox)
                observation=c['sources'][-1]
                for row in rows:
                    observation['input_source_ids'].append(source(c,row['text'],'ocr_text',score(row['confidence'],'ocr_native_0_100',line_provider),photo['photo_id'],row['bbox']))
                if 'provider' not in line and photo['quality']=='readable' and assess_line(text,conf['value'] if conf else None,rows)[0]=='useful': self.extract(c,text,sid,conf)
        stage('classification')
        for key,value in initial.get('fields',{}).items():
            if value and value.strip():
                sid=source(c,value);add_candidate(c,next(f for f in c['fields'] if f['field_id']==key),value,sid,user=True)
        if initial.get('category','unknown').strip() not in ('','unknown'):
            value=initial['category'].strip();c['category'].update(selected=value,reviewed=True,source_ids=[source(c,value)])
        for f in c['fields']: f['required']=f['field_id']=='product_name'
        stage('validation');c['description']=template(c);moderate(c);stage('draft')
        return c
