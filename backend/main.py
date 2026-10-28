import asyncio
import io
import json
import os
import queue
import secrets
import sqlite3
import threading
from contextlib import asynccontextmanager
from datetime import datetime,timedelta,timezone
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parents[1]/'.env',override=False)
from typing import Annotated
import jsonschema
import yaml
from fastapi import FastAPI,Request,UploadFile,File,Form,Query
from fastapi.responses import JSONResponse,FileResponse,Response,HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.docs import get_swagger_ui_html
from PIL import Image,ImageOps,UnidentifiedImageError
from .domain import now,uid,moderate,patch,template,LABELS,REQUIRED,name_requirement
from . import cloud_ocr
from .inference import Providers,ROOT
from .catalog import list_templates,get_template,category_profile,CatalogError
from .preview import preview,render_html
from .recommendations import recommendations
from .photo_analysis import card_recommendations as photo_recommendations
from .ocr_review import ocr_review
from .version import API_VERSION
from . import llm
from .attributes import CATALOG

DATA=Path(os.getenv('DATA_DIR',str(ROOT/'runtime')))/'v2.3';DATA.mkdir(parents=True,exist_ok=True)
PHOTOS=DATA/'photos';PHOTOS.mkdir(exist_ok=True)
DB=DATA/'store.sqlite3'
ORIGINS=set(os.getenv('ALLOWED_ORIGINS','http://localhost:8000,http://127.0.0.1:8000').split(','))
TTL=int(os.getenv('TTL_SECONDS','86400'))
LOCK=threading.RLock(); Q=queue.Queue(maxsize=8); STOP=threading.Event()
PROVIDERS=None
CONTRACT=yaml.safe_load((ROOT/'contracts/openapi.yaml').read_text(encoding='utf-8'))
SCHEMA=json.loads((ROOT/'contracts/card.schema.json').read_text(encoding='utf-8'))
def db():
    conn=sqlite3.connect(DB,timeout=10);conn.row_factory=sqlite3.Row;return conn
def initialize():
    with db() as c:
        c.execute('CREATE TABLE IF NOT EXISTS objects (id TEXT PRIMARY KEY, kind TEXT, session TEXT, expires TEXT, body TEXT)')
        c.execute('CREATE INDEX IF NOT EXISTS expiry ON objects(expires)')
        for row in c.execute("SELECT id,body FROM objects WHERE kind='card'").fetchall():
            card=json.loads(row['body'])
            if name_requirement(card):
                card['revision']+=1;card['confirmation']=None
                moderate(card);jsonschema.validate(card,SCHEMA)
                c.execute('UPDATE objects SET body=? WHERE id=?',(json.dumps(card,ensure_ascii=False),row['id']))
        for row in c.execute("SELECT * FROM objects WHERE kind='job'").fetchall():
            j=json.loads(row['body'])
            if j['status'] in ('queued','running'):
                j.update(status='failed',stage='failed',error=detail('INTERRUPTED','Сервер перезапущен. Отправьте фотографии повторно.'))
                c.execute('UPDATE objects SET body=? WHERE id=?',(json.dumps(j),row['id']))
def detail(code,message,details=None): return dict(code=code,message=message,request_id=uid(),details=details or {})
class APIError(Exception):
    def __init__(self,status,code,message,details=None): self.status=status;self.error=detail(code,message,details)
def save(kind,obj,session):
    key=obj.get('card_id') or obj.get('job_id') or obj.get('photo_id')
    with db() as c:c.execute('INSERT OR REPLACE INTO objects VALUES (?,?,?,?,?)',(key,kind,session,obj['expires_at'],json.dumps(obj,ensure_ascii=False)))
def load(key,kind,session):
    with db() as c: row=c.execute('SELECT * FROM objects WHERE id=? AND kind=? AND session=? AND expires>?',(key,kind,session,now())).fetchone()
    if not row: raise APIError(404,'NOT_FOUND','Данные недоступны или срок хранения истёк. Начните новую загрузку.')
    return json.loads(row['body'])
def cleanup():
    with LOCK,db() as c:
        for row in c.execute("SELECT * FROM objects WHERE expires<=?",(now(),)).fetchall():
            if row['kind']=='photo': (PHOTOS/(row['id']+'.png')).unlink(missing_ok=True)
        c.execute('DELETE FROM objects WHERE expires<=?',(now(),))
def worker():
    while not STOP.is_set():
        try: task=Q.get(timeout=1)
        except queue.Empty:
            cleanup();continue
        job,session,photos,paths,initial=task
        def stage(s):
            job.update(status='running',stage=s);save('job',job,session)
        try:
            card=PROVIDERS.analyze(photos,paths,initial,stage)
            card['expires_at']=job['expires_at'];jsonschema.validate(card,SCHEMA)
            save('card',card,session);job.update(status='succeeded',stage='done',result_card_id=card['card_id'])
        except Exception as e:
            # No raw exceptions, photo text or server paths are returned/logged.
            job.update(status='failed',stage='failed',error=detail('PROVIDER_UNAVAILABLE','Не удалось обработать фотографии. Проверьте OCR-провайдер и повторите загрузку.',{'type':type(e).__name__}))
        save('job',job,session);Q.task_done()
@asynccontextmanager
async def lifespan(app):
    global PROVIDERS
    initialize();cleanup();STOP.clear();PROVIDERS=Providers()
    await asyncio.to_thread(PROVIDERS.check)
    thread=threading.Thread(target=worker,daemon=True);thread.start()
    yield
    STOP.set();thread.join(timeout=2)
app=FastAPI(title='Карточка товара за три минуты',lifespan=lifespan,docs_url=None,redoc_url=None)
app.openapi=lambda:CONTRACT
@app.exception_handler(APIError)
async def api_error(request,exc):return JSONResponse({'error':exc.error},status_code=exc.status,headers={'Retry-After':'10'} if exc.status==429 else {})
@app.exception_handler(CatalogError)
async def catalog_error(request,exc):return JSONResponse({'error':detail(exc.code,exc.message)},status_code=exc.status)
@app.exception_handler(llm.LLMError)
async def llm_error(request,exc):return JSONResponse({'error':detail(exc.code,exc.message)},status_code=exc.status)
@app.exception_handler(RequestValidationError)
async def request_error(request,exc):return JSONResponse({'error':detail('VALIDATION_ERROR','Проверьте обязательные параметры запроса')},status_code=422)
@app.middleware('http')
async def guard(request,call_next):
    if request.method in ('POST','PATCH','PUT','DELETE') and request.headers.get('origin') not in ORIGINS:
        return JSONResponse({'error':detail('ORIGIN_REJECTED','Недопустимый Origin')},status_code=403)
    r=await call_next(request)
    r.headers['X-Content-Type-Options']='nosniff';r.headers['Referrer-Policy']='same-origin';r.headers['Cache-Control']='no-store'
    r.headers['Content-Security-Policy']="default-src 'self'; img-src 'self' blob: data:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'"
    if request.url.path=='/docs':r.headers['Content-Security-Policy']="default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'"
    return r
def validate(name,value):
    schema={'$ref':f'#/components/schemas/{name}','components':CONTRACT['components']}
    try: jsonschema.Draft202012Validator(schema).validate(value)
    except jsonschema.ValidationError as e: raise APIError(422,'VALIDATION_ERROR','Проверьте формат запроса',{'path':list(e.absolute_path),'reason':e.message[:180]})
def session(request): return request.cookies.get('card_session','')
@app.get('/health/live')
def live():return {'status':'ok','providers':{'api_version':API_VERSION}}
@app.get('/api/v1/version')
def version_info():
    return {'api_version':API_VERSION,'features':{'templates':True,'preview_json':True,'preview_html':True,'recommendations':True,'dual_ocr':True,'universal_products':True,'copy_ocr':True,'manual_drafts':True,'opt_in_suggestions':True,'product_library':True,'attribute_builder':True,'llm_assistance':True,'reliable_editor':True},
            'editor_integration':{'template_selector':True,'preview_button':True},'ocr_parser':'ru-en-ppocrv5-triage-v4'}
@app.get('/health/ready')
def ready():
    ok=bool(PROVIDERS and (PROVIDERS.ready or cloud_ocr.configured()))
    return JSONResponse({'status':'ok' if ok else 'not_ready','providers':{'ocr':PROVIDERS.reason if PROVIDERS else 'loading','classifier':'if/else RU+EN text headings; no category restriction; no model score','description':'LLM настроена' if llm.settings()[3] else 'template; LLM не настроена','ocr_modes':PROVIDERS.modes() if PROVIDERS else []}},status_code=200 if ok else 503)
@app.get('/api/v1/config')
def config():return {'attribute_catalog':[dict(field_id=k,label=v) for k,v in CATALOG.items()],'llm':llm.public_config(),'labels':LABELS,'required_total':len(REQUIRED),'processing':'Выберите локальную модель или Google Cloud Vision API. Только в режиме API фотографии передаются Google. Данные прототипа хранятся 24 часа.','classifier':'Классификация текстовых строк по явным RU/EN заголовкам (if/else). Категорийных ограничений нет; model score не создаётся.','ocr_modes':PROVIDERS.modes() if PROVIDERS else []}
@app.get('/docs',include_in_schema=False)
def docs():return get_swagger_ui_html(openapi_url='/openapi.json',title='Полка — API',swagger_js_url='/swagger/swagger-ui-bundle.js',swagger_css_url='/swagger/swagger-ui.css',swagger_favicon_url='/swagger/favicon-32x32.png')
@app.post('/api/v1/jobs',status_code=202)
async def create_job(request:Request,files:Annotated[list[UploadFile],File()],initial_data:Annotated[str,Form()]='{}'):
    if not 1<=len(files)<=3:raise APIError(422,'VALIDATION_ERROR','Загрузите от 1 до 3 фотографий')
    try:initial=json.loads(initial_data)
    except ValueError:raise APIError(422,'VALIDATION_ERROR','initial_data должен быть JSON')
    validate('InitialData',initial)
    mode=initial.get('ocr_mode','local')
    if not PROVIDERS or not PROVIDERS.available(mode):raise APIError(503,'PROVIDER_UNAVAILABLE','Локальная модель не установлена на сервере.' if mode=='local' else 'Google Cloud Vision пока не подключён на сервере. Выберите локальную модель.')
    if any(v and len(v)>4000 for v in initial.get('fields',{}).values()):raise APIError(422,'VALIDATION_ERROR','Поле длиннее 4000 символов')
    owner=session(request) or secrets.token_urlsafe(32)
    with LOCK:
        with db() as c: previous=[json.loads(r['body']) for r in c.execute("SELECT body FROM objects WHERE kind='job' AND session=? AND expires>?",(owner,now()))]
        if any(j['status'] in ('queued','running') for j in previous):raise APIError(429,'RATE_LIMITED','Дождитесь завершения текущей задачи')
        if sum(j['created_at']>(datetime.now(timezone.utc)-timedelta(hours=1)).isoformat() for j in previous)>=10:raise APIError(429,'RATE_LIMITED','Лимит — 10 задач в час на сессию')
        with db() as c: active=c.execute("SELECT COUNT(*) FROM objects WHERE kind='job' AND expires>?",(now(),)).fetchone()[0]
        if Q.full() or active>=int(os.getenv('GLOBAL_JOB_BUDGET','200')):raise APIError(429,'QUEUE_FULL','Общий лимит обработки достигнут. Повторите позже.')
    photos=[];paths=[];normalized=[]
    for upload in files:
        raw=await upload.read(5*1024*1024+1)
        if len(raw)>5*1024*1024:raise APIError(413,'UPLOAD_TOO_LARGE','Максимум 5 MiB на файл')
        if upload.content_type not in ('image/jpeg','image/png'):raise APIError(415,'UNSUPPORTED_MEDIA_TYPE','Принимаются JPEG и PNG')
        try:
            im=Image.open(io.BytesIO(raw))
            if im.format not in ('JPEG','PNG'):raise APIError(415,'UNSUPPORTED_MEDIA_TYPE','Содержимое файла не JPEG/PNG')
            if upload.content_type!={'JPEG':'image/jpeg','PNG':'image/png'}[im.format]:raise APIError(415,'UNSUPPORTED_MEDIA_TYPE','MIME не совпадает с содержимым изображения')
            if im.width*im.height>20_000_000:raise APIError(413,'UPLOAD_TOO_LARGE','Лимит — 20 миллионов пикселей')
            im.load();im=ImageOps.exif_transpose(im).convert('RGB');im.info.clear()
        except APIError:raise
        except (UnidentifiedImageError,OSError,ValueError,Image.DecompressionBombError):raise APIError(422,'VALIDATION_ERROR','Повреждённое или слишком большое изображение')
        pid=uid();photos.append(dict(photo_id=pid,url=f'/api/v1/photos/{pid}',width=im.width,height=im.height,quality='uncertain'));normalized.append(im)
    expiry=(datetime.now(timezone.utc)+timedelta(seconds=TTL)).isoformat()
    job=dict(job_id=uid(),ocr_mode=mode,status='queued',stage='queued',result_card_id=None,error=None,created_at=now(),expires_at=expiry)
    with LOCK:
        # Recheck active owner and queue while serializing enqueue and storage.
        with db() as c:
            rows=c.execute("SELECT body FROM objects WHERE kind='job' AND session=? AND expires>?",(owner,now())).fetchall()
        latest=[json.loads(r['body']) for r in rows]
        if any(j['status'] in ('queued','running') for j in latest) or Q.full():raise APIError(429,'QUEUE_FULL','Задача уже обрабатывается или очередь заполнена')
        if sum(j['created_at']>(datetime.now(timezone.utc)-timedelta(hours=1)).isoformat() for j in latest)>=10:raise APIError(429,'RATE_LIMITED','Лимит — 10 задач в час на сессию')
        with db() as c:budget=c.execute("SELECT COUNT(*) FROM objects WHERE kind='job' AND expires>?",(now(),)).fetchone()[0]
        if budget>=int(os.getenv('GLOBAL_JOB_BUDGET','200')):raise APIError(429,'QUEUE_FULL','Общий лимит обработки достигнут')
        for photo,im in zip(photos,normalized):
            path=PHOTOS/(photo['photo_id']+'.png');im.save(path);paths.append(path);save('photo',{**photo,'expires_at':expiry},owner)
        save('job',job,owner);Q.put_nowait((job.copy(),owner,photos,paths,initial))
    response=JSONResponse(job,status_code=202);response.set_cookie('card_session',owner,httponly=True,samesite='lax',secure=request.url.scheme=='https',max_age=86400)
    return response
@app.get('/api/v1/jobs/{key}')
def get_job(key:str,request:Request):return load(key,'job',session(request))
@app.get('/api/v1/cards/{key}')
def get_card(key:str,request:Request):return load(key,'card',session(request))
@app.get('/api/v1/templates')
def templates():
    return {'templates':list_templates(),'category_profiles':[category_profile('unknown')]}
@app.get('/api/v1/templates/{template_id}')
def template_detail(template_id:str,version:Annotated[int,Query(ge=1)]):return get_template(template_id,version)
def revision_snapshot(key,request,expected_revision):
    c=load(key,'card',session(request))
    if c['revision']!=expected_revision:raise APIError(409,'REVISION_CONFLICT','Карточка уже изменена',{'revision':c['revision']})
    return c
@app.get('/api/v1/cards/{key}/preview')
def card_preview(key:str,request:Request,template_id:str,template_version:Annotated[int,Query(ge=1)],expected_revision:Annotated[int,Query(ge=1)]):
    c=revision_snapshot(key,request,expected_revision)
    return preview(c,template_id,template_version)
@app.get('/api/v1/cards/{key}/preview.html',response_class=HTMLResponse)
def card_preview_html(key:str,request:Request,template_id:str,template_version:Annotated[int,Query(ge=1)],expected_revision:Annotated[int,Query(ge=1)],palette:Annotated[str,Query(pattern='^(strata|ocean|sage|clay)$')]='strata'):
    c=revision_snapshot(key,request,expected_revision)
    return HTMLResponse(render_html(preview(c,template_id,template_version),palette))
@app.get('/api/v1/cards/{key}/recommendations')
def card_recommendations(key:str,request:Request,expected_revision:Annotated[int,Query(ge=1)]):
    return photo_recommendations(revision_snapshot(key,request,expected_revision), session(request), sys.modules[__name__])
@app.get('/api/v1/cards/{key}/ocr-review')
def card_ocr_review(key:str,request:Request,expected_revision:Annotated[int,Query(ge=1)]):
    return ocr_review(revision_snapshot(key,request,expected_revision))
@app.get('/api/v1/photos/{key}')
def get_photo(key:str,request:Request):
    load(key,'photo',session(request));return FileResponse(PHOTOS/(key+'.png'),media_type='image/png')
async def body(request,name):
    raw=await request.body()
    if len(raw)>100_000:raise APIError(413,'UPLOAD_TOO_LARGE','Слишком большой запрос')
    try: p=json.loads(raw)
    except ValueError:raise APIError(422,'VALIDATION_ERROR','Ожидается JSON')
    validate(name,p);return p
def mutate(key,owner,p,confirm=False,regenerate=False):
    with LOCK,db() as conn:
        conn.execute('BEGIN IMMEDIATE')
        row=conn.execute("SELECT body FROM objects WHERE id=? AND kind='card' AND session=? AND expires>?",(key,owner,now())).fetchone()
        if not row:raise APIError(404,'NOT_FOUND','Карточка недоступна или истекла')
        card=json.loads(row['body'])
        if card['revision']!=p['expected_revision']:raise APIError(409,'REVISION_CONFLICT','Карточка уже изменена',{'revision':card['revision']})
        if confirm:
            moderate(card)
            if card['readiness']['state']=='confirmed':return card
            if card['readiness']['state']!='ready_to_confirm':raise APIError(409,'CARD_NOT_READY','Исправьте блокирующие замечания',{'readiness':card['readiness']})
            card['revision']+=1;card['confirmation']=dict(confirmed_revision=card['revision'],confirmed_at=now());moderate(card)
        elif regenerate:
            card['description']=template(card);card['revision']+=1;card['confirmation']=None;moderate(card)
        else:
            try: card=patch(card,p)
            except ValueError as error: raise APIError(422,'VALIDATION_ERROR',str(error)) from None
        jsonschema.validate(card,SCHEMA)
        conn.execute('UPDATE objects SET body=? WHERE id=?',(json.dumps(card,ensure_ascii=False),key))
        return card
@app.patch('/api/v1/cards/{key}')
async def patch_card(key:str,request:Request):
    p=await body(request,'PatchCard');keys=[u['field_id'] for u in p.get('field_updates',[])]
    if len(keys)!=len(set(keys)): raise APIError(422,'VALIDATION_ERROR','Каждое поле допускается в запросе только один раз')
    return mutate(key,session(request),p)
@app.post('/api/v1/cards/{key}/confirm')
async def confirm_card(key:str,request:Request):return mutate(key,session(request),await body(request,'ConfirmCard'),True)
@app.post('/api/v1/cards/{key}/description-template')
async def description_template(key:str,request:Request):return mutate(key,session(request),await body(request,'ConfirmCard'),regenerate=True)
@app.get('/api/v1/cards/{key}/export')
def export(key:str,request:Request,format:Annotated[str,Query(pattern='^(json|text)$')]='json'):
    c=moderate(load(key,'card',session(request)))
    if c['readiness']['state']!='confirmed':raise APIError(409,'CARD_NOT_READY','Сначала вручную подтвердите текущую ревизию')
    if format=='text':
        return Response(c['description']['text']+'\n',media_type='text/plain; charset=utf-8',headers={'Content-Disposition':f'attachment; filename="product-{key}.txt"'})
    return Response(json.dumps(c,ensure_ascii=False,indent=2),media_type='application/json',headers={'Content-Disposition':f'attachment; filename="card-{key}.json"'})
@app.get('/demo/{name}.png')
def demo(name:str):
    if name not in ('dairy','jam','missing','conflict','other','blur','cable'):raise APIError(404,'NOT_FOUND','Пример не найден')
    return FileResponse(ROOT/'data/demo'/f'{name}.png')
from .manual_routes import register as register_manual_routes
import sys
register_manual_routes(app, sys.modules[__name__])
from .llm_routes import register as register_llm_routes
register_llm_routes(app, sys.modules[__name__])
if (ROOT/'node_modules/swagger-ui-dist').exists():app.mount('/swagger',StaticFiles(directory=ROOT/'node_modules/swagger-ui-dist'),name='swagger')
app.mount('/',StaticFiles(directory=ROOT/'frontend',html=True),name='frontend')
