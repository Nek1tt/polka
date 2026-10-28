"""Manual drafts and opt-in OCR suggestions. Inference never mutates the working card."""
import copy
import io
import json
import secrets
import os
from datetime import datetime, timedelta, timezone

import jsonschema
from fastapi import File, Form, Query, Request, UploadFile
from fastapi.responses import JSONResponse
from PIL import Image, ImageOps, UnidentifiedImageError
from typing import Annotated

from .domain import blank, moderate, now, source, template, uid, field_label
from .ocr_review import ocr_review


def register(app, a):
    def store(conn, card, owner):
        jsonschema.validate(card, a.SCHEMA)
        conn.execute('UPDATE objects SET body=? WHERE id=? AND kind=\'card\' AND session=?',
                     (json.dumps(card, ensure_ascii=False), card['card_id'], owner))

    def locked_card(conn, key, owner, revision):
        row = conn.execute("SELECT body FROM objects WHERE id=? AND kind='card' AND session=? AND expires>?",
                           (key, owner, now())).fetchone()
        if not row:
            raise a.APIError(404, 'NOT_FOUND', 'Карточка недоступна или истекла')
        card = json.loads(row['body'])
        if card['revision'] != revision:
            raise a.APIError(409, 'REVISION_CONFLICT', 'Карточка уже изменена. Обновите её перед действием.')
        return card

    def analysis(key, owner, job_id):
        binding = a.load(job_id + '-binding', 'ocr_binding', owner)
        if binding['base_card_id'] != key:
            raise a.APIError(404, 'NOT_FOUND', 'Подсказки относятся к другой карточке')
        job = a.load(job_id, 'job', owner)
        if job['status'] != 'succeeded':
            raise a.APIError(409, 'OCR_NOT_READY', 'Распознавание ещё не завершено или закончилось ошибкой')
        result = a.load(job['result_card_id'], 'card', owner)
        mapping = dict(zip([p['photo_id'] for p in result['photos']], binding['photo_ids'], strict=True))
        original = a.load(key, 'card', owner)
        photos = {p['photo_id']: p for p in original['photos']}
        if not set(mapping.values()).issubset(photos):
            raise a.APIError(409, 'PHOTOS_CHANGED', 'Фотографии изменились. Запустите распознавание снова.')
        result = copy.deepcopy(result)
        for photo in result['photos']:
            photo.update(photo_id=mapping[photo['photo_id']], url=photos[mapping[photo['photo_id']]]['url'])
        for observation in result['sources']:
            if observation['photo_id']:
                observation['photo_id'] = mapping[observation['photo_id']]
        return result

    @app.post('/api/v1/cards', status_code=201)
    async def create_manual(request: Request):
        data = await a.body(request, 'ManualCardCreate')
        owner = a.session(request) or secrets.token_urlsafe(32)
        with a.LOCK:
            with a.db() as conn:
                recent = conn.execute("SELECT body FROM objects WHERE kind='card' AND session=? AND expires>?", (owner, now())).fetchall()
            if len(recent) >= 100:
                raise a.APIError(429, 'RATE_LIMITED', 'Лимит — 100 активных карточек на сессию')
            card = blank([])
            from .attributes import new_field
            keys = list(dict.fromkeys(['product_name', *data.get('fields', {}), *data.get('required_fields', [])]))
            card['fields'] = [new_field(key) for key in keys]
            card['expires_at'] = (datetime.now(timezone.utc) + timedelta(seconds=a.TTL)).isoformat()
            for field in card['fields']:
                value = (data.get('fields', {}).get(field['field_id']) or '').strip()
                field['required'] = field['field_id'] == 'product_name'
                if value:
                    sid = source(card, value)
                    field.update(value=value, source_ids=[sid], status='suggested', reviewed=False)
            if data.get('category', '').strip() not in ('', 'unknown'):
                value = data['category'].strip()
                card['category'].update(selected=value, reviewed=False, source_ids=[source(card, value)])
            moderate(card)
            jsonschema.validate(card, a.SCHEMA)
            a.save('card', card, owner)
        response = JSONResponse(card, status_code=201)
        response.set_cookie('card_session', owner, httponly=True, samesite='lax', secure=request.url.scheme == 'https', max_age=86400)
        return response

    @app.get('/api/v1/cards')
    def list_cards(request: Request):
        # OCR result cards are internal analyses, not additional products.
        with a.LOCK, a.db() as conn:
            rows = conn.execute('SELECT kind, body FROM objects WHERE session=? AND expires>?', (a.session(request), now())).fetchall()
        objects = [(row['kind'], json.loads(row['body'])) for row in rows]
        analyses = {obj.get('result_card_id') for kind, obj in objects if kind == 'job'}
        items = []
        for kind, card in objects:
            if kind != 'card' or card['card_id'] in analyses:
                continue
            moderate(card)
            items.append(dict(card_id=card['card_id'], revision=card['revision'],
                title=next(f['value'] for f in card['fields'] if f['field_id'] == 'product_name') or 'Без названия',
                created_at=card['created_at'], expires_at=card['expires_at'],
                photo_url=card['photos'][0]['url'] if card['photos'] else None,
                state=card['readiness']['state']))
        return dict(cards=sorted(items, key=lambda item: item['created_at'], reverse=True))

    @app.delete('/api/v1/cards/{key}')
    def delete_card(key: str, request: Request, expected_revision: int = Query(ge=1)):
        owner = a.session(request)
        with a.LOCK, a.db() as conn:
            conn.execute('BEGIN IMMEDIATE')
            card = locked_card(conn, key, owner, expected_revision)
            rows = conn.execute('SELECT id, kind, body FROM objects WHERE session=?', (owner,)).fetchall()
            objects = {row['id']: (row['kind'], json.loads(row['body'])) for row in rows}
            ids = {key}
            photos = {p['photo_id'] for p in card['photos']}
            for oid, (kind, obj) in objects.items():
                if kind == 'ocr_binding' and obj['base_card_id'] == key:
                    job_id = oid.removesuffix('-binding')
                    job = objects.get(job_id, (None, {}))[1]
                    if job.get('status') in ('queued', 'running'):
                        raise a.APIError(409, 'OCR_IN_PROGRESS', 'Дождитесь завершения распознавания перед удалением товара')
                    ids.update([oid, job_id])
                    if job.get('result_card_id'):
                        ids.add(job['result_card_id'])
                elif kind == 'llm_analysis' and obj.get('card_id') == key:
                    ids.add(oid)
                elif kind == 'job' and obj.get('result_card_id') == key:
                    ids.add(oid)
            # Retain any photo still used by another product/analysis.
            shared = {p['photo_id'] for oid, (kind, obj) in objects.items() if kind == 'card' and oid not in ids for p in obj['photos']}
            photos -= shared
            ids.update(photos)
            conn.executemany('DELETE FROM objects WHERE id=? AND session=?', [(oid, owner) for oid in ids])
        for pid in photos:
            (a.PHOTOS / (pid + '.png')).unlink(missing_ok=True)
        return dict(deleted=True, card_id=key)

    @app.post('/api/v1/cards/{key}/photos')
    async def attach_photos(key: str, request: Request, files: Annotated[list[UploadFile], File()], expected_revision: Annotated[int, Form()]):
        owner = a.session(request)
        current = a.revision_snapshot(key, request, expected_revision)
        if not files or len(files) + len(current['photos']) > 3:
            raise a.APIError(422, 'VALIDATION_ERROR', 'В карточке может быть до трёх фотографий')
        prepared = []
        for upload in files:
            raw = await upload.read(5 * 1024 * 1024 + 1)
            if len(raw) > 5 * 1024 * 1024:
                raise a.APIError(413, 'UPLOAD_TOO_LARGE', 'Максимум 5 MiB на файл')
            if upload.content_type not in ('image/jpeg', 'image/png'):
                raise a.APIError(415, 'UNSUPPORTED_MEDIA_TYPE', 'Принимаются JPEG и PNG')
            try:
                image = Image.open(io.BytesIO(raw))
                if image.format not in ('JPEG', 'PNG') or upload.content_type != {'JPEG': 'image/jpeg', 'PNG': 'image/png'}[image.format]:
                    raise a.APIError(415, 'UNSUPPORTED_MEDIA_TYPE', 'MIME не совпадает с изображением')
                if image.width * image.height > 20_000_000:
                    raise a.APIError(413, 'UPLOAD_TOO_LARGE', 'Лимит — 20 миллионов пикселей')
                image.load()
                image = ImageOps.exif_transpose(image).convert('RGB')
                image.info.clear()
            except a.APIError:
                raise
            except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
                raise a.APIError(422, 'VALIDATION_ERROR', 'Повреждённое или слишком большое изображение')
            prepared.append(image)
        with a.LOCK, a.db() as conn:
            conn.execute('BEGIN IMMEDIATE')
            card = locked_card(conn, key, owner, expected_revision)
            for image in prepared:
                pid = uid()
                photo = dict(photo_id=pid, url=f'/api/v1/photos/{pid}', width=image.width, height=image.height, quality='not_analyzed')
                image.save(a.PHOTOS / (pid + '.png'))
                conn.execute('INSERT INTO objects VALUES (?,?,?,?,?)', (pid, 'photo', owner, card['expires_at'], json.dumps({**photo, 'expires_at': card['expires_at']})))
                card['photos'].append(photo)
            card['revision'] += 1
            card['confirmation'] = None
            card['description']['reviewed'] = False
            moderate(card)
            store(conn, card, owner)
        return card

    @app.post('/api/v1/cards/{key}/ocr-jobs', status_code=202)
    async def suggest(key: str, request: Request):
        data = await a.body(request, 'SuggestionJobCreate')
        card = a.revision_snapshot(key, request, data['expected_revision'])
        if not card['photos']:
            raise a.APIError(422, 'PHOTOS_REQUIRED', 'Добавьте фотографию для распознавания')
        owner = a.session(request)
        mode = data['ocr_mode']
        if not a.PROVIDERS or not a.PROVIDERS.available(mode):
            raise a.APIError(503, 'PROVIDER_UNAVAILABLE', 'Выбранный OCR-провайдер не настроен. Редактор продолжает работать.')
        photos = copy.deepcopy(card['photos'])
        paths = []
        for photo in photos:
            a.load(photo['photo_id'], 'photo', owner)
            paths.append(a.PHOTOS / (photo['photo_id'] + '.png'))
        job = dict(job_id=uid(), ocr_mode=mode, status='queued', stage='queued', result_card_id=None,
                   error=None, created_at=now(), expires_at=card['expires_at'])
        with a.LOCK:
            with a.db() as conn:
                previous = [json.loads(r['body']) for r in conn.execute("SELECT body FROM objects WHERE kind='job' AND session=? AND expires>?", (owner, now()))]
                count = conn.execute("SELECT COUNT(*) FROM objects WHERE kind='job' AND expires>?", (now(),)).fetchone()[0]
            if any(j['status'] in ('queued', 'running') for j in previous):
                raise a.APIError(429, 'RATE_LIMITED', 'Дождитесь завершения текущего распознавания')
            if sum(j['created_at'] > (datetime.now(timezone.utc)-timedelta(hours=1)).isoformat() for j in previous) >= 10:
                raise a.APIError(429, 'RATE_LIMITED', 'Лимит — 10 задач в час на сессию')
            if a.Q.full() or count >= int(os.getenv('GLOBAL_JOB_BUDGET', '200')):
                raise a.APIError(429, 'QUEUE_FULL', 'Очередь заполнена. Повторите позже.')
            a.save('job', job, owner)
            a.save('ocr_binding', dict(photo_id=job['job_id'] + '-binding', base_card_id=key,
                                     photo_ids=[p['photo_id'] for p in photos], expires_at=job['expires_at']), owner)
            a.Q.put_nowait((job.copy(), owner, photos, paths, {'ocr_mode': mode}))
        return JSONResponse(job, status_code=202)

    @app.get('/api/v1/cards/{key}/ocr-suggestions')
    def suggestions(key: str, request: Request, job_id: str = Query(min_length=1)):
        result = analysis(key, a.session(request), job_id)
        return dict(job_id=job_id, analysis_card=result, review=ocr_review(result))

    @app.post('/api/v1/cards/{key}/accept-suggestion')
    async def accept(key: str, request: Request):
        data = await a.body(request, 'AcceptSuggestion')
        owner = a.session(request)
        result = analysis(key, owner, data['job_id'])
        line = next((line for line in ocr_review(result)['lines'] if line['group'] != 'doubtful' and sorted(line['source_ids']) == sorted(data['source_ids'])), None)
        if not line:
            raise a.APIError(422, 'INVALID_SUGGESTION', 'Строка не является доступной подсказкой')
        value = line['suggested_value'] if line['field_id'] == data['field_id'] and line['suggested_value'] else line['text']
        with a.LOCK, a.db() as conn:
            conn.execute('BEGIN IMMEDIATE')
            card = locked_card(conn, key, owner, data['expected_revision'])
            field = next((f for f in card['fields'] if f['field_id'] == data['field_id']), None)
            if field is None:
                from .attributes import CATALOG, new_field
                if data['field_id'] not in CATALOG or len(card['fields'])>=80:
                    raise a.APIError(422,'FIELD_NOT_SELECTED','Сначала добавьте характеристику в конструкторе')
                field=new_field(data['field_id']);card['fields'].append(field)
            if field['status'] == 'conflict':
                raise a.APIError(409, 'UNRESOLVED_CONFLICT', 'Сначала разрешите противоречие в поле')
            if field['value'] and field['value'] != value and not data.get('replace_existing', False):
                raise a.APIError(409, 'FIELD_HAS_VALUE', 'Поле уже заполнено. Замена требует отдельного выбора.')
            sources = {s['source_id']: s for s in result['sources']}
            existing = {s['source_id'] for s in card['sources']}
            def include(sid):
                if sid in existing:
                    return
                observation = copy.deepcopy(sources[sid])
                for dependency in observation['input_source_ids']:
                    include(dependency)
                card['sources'].append(observation)
                existing.add(sid)
            for sid in line['source_ids']:
                include(sid)
            field.setdefault('label', field_label(field))
            field['candidates'].append(dict(value=value, source_ids=line['source_ids'], confidence=line['confidence']))
            field.update(value=value, source_ids=line['source_ids'], confidence=line['confidence'], reviewed=False, status='suggested')
            card['ocr'] = copy.deepcopy(result['ocr'])
            card['description'] = template(card) if card['description']['mode'] == 'template' else {**card['description'], 'reviewed': False}
            card['revision'] += 1
            card['confirmation'] = None
            moderate(card)
            store(conn, card, owner)
        return card
