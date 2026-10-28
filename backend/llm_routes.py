"""Revision-bound, session-private LLM proposals, explicitly applied by the seller."""
import json
import os
import logging
from datetime import datetime, timedelta, timezone
from . import llm
from .domain import now, uid, moderate

def public(analysis): return {k:v for k,v in analysis.items() if k not in ('job_id','status','created_at')}

def register(app, a):
    def save_analysis(item,owner):
        with a.LOCK,a.db() as conn:
            conn.execute("UPDATE objects SET body=? WHERE id=? AND kind='llm_analysis' AND session=?",(json.dumps(item,ensure_ascii=False),item['analysis_id'],owner))
    @app.post('/api/v1/cards/{key}/text-assistance')
    async def analyze(key: str, request: a.Request):
        p = await a.body(request, 'TextAssistanceRequest')
        card = a.revision_snapshot(key, request, p['expected_revision'])
        if not p['allow_external_processing']:
            raise a.APIError(422,'EXTERNAL_PROCESSING_REQUIRED','Для LLM нужно явно разрешить отправку текста провайдеру.')
        if not llm.settings()[3]:
            raise a.APIError(503,'LLM_NOT_CONFIGURED','Добавьте серверный ключ LLM в .env. Редактор и OCR продолжают работать.')
        data = llm.inputs(card)
        owner = a.session(request)
        provider, model, _, _ = llm.settings()
        with a.LOCK, a.db() as conn:
            conn.execute('BEGIN IMMEDIATE')
            rows = conn.execute("SELECT session,body FROM objects WHERE kind='llm_analysis' AND expires>?", (now(),)).fetchall()
            previous = [(r['session'],json.loads(r['body'])) for r in rows]
            for session, item in previous:
                if session==owner and item['card_id']==key and item['card_revision']==card['revision'] and item['model']==model and item['provider']==provider and item['status']=='succeeded' and item['prompt_version']==llm.PROMPT_VERSION:
                    return public(item)
            attempts=[(r['session'],json.loads(r['body'])) for r in conn.execute("SELECT session,body FROM objects WHERE kind='llm_attempt' AND expires>?",(now(),))]
            if sum(s==owner and i['created_at']>(datetime.now(timezone.utc)-timedelta(hours=1)).isoformat() for s,i in attempts)>=10:
                raise a.APIError(429,'LLM_RATE_LIMIT','Лимит сервиса — 10 анализов в час на сессию.')
            if len(attempts)>=int(os.getenv('LLM_DAILY_BUDGET','40')):
                raise a.APIError(429,'LLM_RATE_LIMIT','Общий бюджет анализов на сутки исчерпан.')
            if any(s==owner and i['status']=='running' and i['created_at']>(datetime.now(timezone.utc)-timedelta(minutes=2)).isoformat() for s,i in previous):
                raise a.APIError(429,'LLM_RATE_LIMIT','Дождитесь завершения текущего анализа.')
            analysis = dict(analysis_id=uid(),card_id=key,card_revision=card['revision'],provider=provider,model=model,
                prompt_version=llm.PROMPT_VERSION,status='running',created_at=now(),expires_at=card['expires_at'])
            analysis['job_id']=analysis['analysis_id']
            conn.execute('INSERT INTO objects VALUES (?,?,?,?,?)',(analysis['analysis_id'],'llm_analysis',owner,analysis['expires_at'],json.dumps(analysis)))
            budget_expiry=(datetime.now(timezone.utc)+timedelta(days=1)).isoformat()
            conn.execute('INSERT INTO objects VALUES (?,?,?,?,?)',(analysis['analysis_id']+'-budget','llm_attempt',owner,budget_expiry,json.dumps(dict(created_at=analysis['created_at']))))
        try:
            analysis['result'] = await llm.generate(data)
            analysis['status'] = 'succeeded'
            save_analysis(analysis, owner)
            a.revision_snapshot(key, request, card['revision'])
            return public(analysis)
        except llm.LLMError as error:
            analysis['status']='failed';analysis['error']=dict(code=error.code,details=error.details);save_analysis(analysis,owner)
            logging.getLogger('polka.llm').warning('LLM request failed: code=%s upstream_status=%s provider=%s',error.code,error.details.get('upstream_status','n/a'),provider)
            raise a.APIError(error.status,error.code,error.message,error.details) from None

    @app.post('/api/v1/cards/{key}/apply-text-assistance')
    async def apply(key: str, request: a.Request):
        p = await a.body(request, 'ApplyTextAssistance')
        owner = a.session(request)
        analysis = a.load(p['analysis_id'],'llm_analysis',owner)
        if analysis['card_id']!=key or analysis['status']!='succeeded':
            raise a.APIError(404,'NOT_FOUND','Предложение недоступно для этой карточки.')
        if analysis['card_revision']!=p['expected_revision']:
            raise a.APIError(409,'REVISION_CONFLICT','После изменения карточки нужен новый анализ текста.')
        with a.LOCK, a.db() as conn:
            conn.execute('BEGIN IMMEDIATE')
            row=conn.execute("SELECT body FROM objects WHERE id=? AND kind='card' AND session=? AND expires>?",(key,owner,now())).fetchone()
            if not row: raise a.APIError(404,'NOT_FOUND','Карточка недоступна.')
            card=json.loads(row['body'])
            if card['revision']!=p['expected_revision']:
                raise a.APIError(409,'REVISION_CONFLICT','Карточка изменилась. Запустите новый анализ.')
            sentences=analysis['result']['description_sentences']
            if not sentences: raise a.APIError(422,'LLM_EMPTY_DESCRIPTION','Модель не предложила описание.')
            facts={f['fact_id']:f for f in llm.inputs(card)['facts']}
            statements=[dict(text=s['text'],source_ids=list(dict.fromkeys(sid for fid in s['fact_ids'] for sid in facts[fid]['source_ids'])),asserted_as_user_input=False) for s in sentences]
            card['description']=dict(text='\n'.join(s['text'] for s in statements),mode='llm',reviewed=False,
                statements=statements,source_ids=list(dict.fromkeys(sid for s in statements for sid in s['source_ids'])))
            card['revision']+=1;card['confirmation']=None;moderate(card)
            a.jsonschema.validate(card,a.SCHEMA)
            conn.execute('UPDATE objects SET body=? WHERE id=?',(json.dumps(card,ensure_ascii=False),key))
        return card
