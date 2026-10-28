import {renderOCR,clearOCR} from './ocr-tools.mjs';
import {selectedAttributes} from './attribute-builder.mjs';
const $=s=>document.querySelector(s);
const make=(tag,text='',className='')=>{const n=document.createElement(tag);n.textContent=text;n.className=className;return n};
export function createManualEditor({api,json,notice,busy,renderCard,savePending,showWorkspace,showSource,onAnalysis=()=>{},getState,setCard}){
 let config,extra=new Set(),jobId=null,result=null,timer=null,pollGeneration=0,skipped=new Set(),loading=false;
 const current=()=>getState().card;
 const key=row=>row.source_ids.join('|');
 function persist(){if(!current())return;try{localStorage.setItem('polka-hints-'+current().card_id,JSON.stringify({jobId,skipped:[...skipped]}))}catch{}}
 function reset(){clearTimeout(timer);pollGeneration++;jobId=null;result=null;skipped.clear();loading=false;extra.clear()}
 async function create(){reset();await busy(async()=>{const draft=await api('/api/v1/cards',json('POST',{}));setCard(draft);renderCard();showWorkspace('editor');notice('')})}
 async function open(id){const draft=await api('/api/v1/cards/'+encodeURIComponent(id));reset();setCard(draft);renderCard();restore();showWorkspace('editor');notice('')}
 function abandon(){reset();clearOCR()}
 async function start(){const id=localStorage.getItem('polka-manual-card');if(id){try{setCard(await api('/api/v1/cards/'+encodeURIComponent(id)));renderCard();restore();return}catch(error){if(!['NOT_FOUND'].includes(error.code))throw error;localStorage.removeItem('polka-manual-card')}}await create()}
 function restore(){try{const saved=JSON.parse(localStorage.getItem('polka-hints-'+current().card_id)||'null');if(saved?.jobId){jobId=saved.jobId;skipped=new Set(saved.skipped||[]);poll(jobId,current().card_id,++pollGeneration)}}catch{}}
 function visibleFields(){return current()?selectedAttributes(current()).map(f=>f.field_id):[]}
 function applyFields(){renderInline()}
 function renderInline(){document.querySelectorAll('.field-suggestions').forEach(node=>node.remove());if(!result)return;const grouped=new Map();for(const row of result.review.lines){if(!row.field_id||row.group!=='useful'||skipped.has(key(row)))continue;if(!grouped.has(row.field_id))grouped.set(row.field_id,[]);grouped.get(row.field_id).push(row)}for(const [id,rows] of grouped){const target=$('#field-'+id);if(!target)continue;const details=make('details','','field-suggestions');details.append(make('summary','Подсказки с фото ('+rows.length+')'));for(const row of rows){details.append(make('p',row.suggested_value||row.text));const actions=make('div','','ocr-actions');for(const [label,action] of [['На фото',()=>showSource(row.photo_id,row.bbox)],['Принять',()=>accept(row,id)],['Пропустить',()=>{skipped.add(key(row));persist();render()}]]){const button=make('button',label,'source-link');button.type='button';button.onclick=action;actions.append(button)}details.append(actions)}target.append(details)}}
 function configure(value){config=value;const select=$('#ocr-mode');select.replaceChildren();for(const mode of config.ocr_modes){const option=make('option',mode.label+(mode.available?'':' — не настроено'));option.value=mode.id;select.append(option)}select.value='local';select.onchange=modeNotice;modeNotice();$('#open-photos').onclick=()=>{showWorkspace('analysis');$('#drop').scrollIntoView({block:'center'})};$('#start-ocr').onclick=runOCR;$('#files').onchange=event=>{const files=[...event.target.files];event.target.value='';if(files.length)attach(files)};$('#drop').ondragover=event=>{event.preventDefault();$('#drop').classList.add('drag')};$('#drop').ondragleave=()=>$('#drop').classList.remove('drag');$('#drop').ondrop=event=>{event.preventDefault();$('#drop').classList.remove('drag');attach([...event.dataTransfer.files])};document.querySelectorAll('[data-demo]').forEach(button=>button.onclick=async()=>{try{const response=await fetch('/demo/'+button.dataset.demo+'.png');if(!response.ok)throw Error('Пример недоступен');if(await attach([new File([await response.blob()],'Синтетический пример.png',{type:'image/png'})]))notice('Добавлена синтетическая тестовая этикетка. OCR запускается отдельно кнопкой «Найти сведения на фото».')}catch(error){notice(error.message)}})}
 function modeNotice(){$('#ocr-mode-notice').textContent=config.ocr_modes.find(m=>m.id===$('#ocr-mode').value)?.notice||''}
 async function attach(files){
  if(!files.length)return false;let attached=false;
  try{await busy(async()=>{
   if(!await savePending())return;
   const base=current();if(base.photos.length+files.length>3){notice('В карточке может быть до трёх фотографий.');return}
   const body=new FormData();for(const file of files)body.append('files',file);body.append('expected_revision',base.revision);
   const updated=await api('/api/v1/cards/'+base.card_id+'/photos',{method:'POST',body});
   setCard(updated);renderCard();attached=true;notice('Фотографии добавлены. Модель не запускалась. Можно продолжать заполнение.','success');
  })}catch(error){notice(error.message)}return attached;
 }
 async function runOCR(){if(loading)return;notice('');const base=current(),mode=$('#ocr-mode').value;if(!base.photos.length){notice('Добавьте фото, если хотите получить подсказки. Редактор работает и без OCR.');return}loading=true;render();try{const job=await api('/api/v1/cards/'+base.card_id+'/ocr-jobs',json('POST',{expected_revision:base.revision,ocr_mode:mode}));if(current().card_id!==base.card_id)return;jobId=job.job_id;result=null;skipped.clear();persist();poll(jobId,base.card_id,++pollGeneration)}catch(error){if(current().card_id===base.card_id){loading=false;render();notice(error.message)}}}
 async function poll(id,cardId,generation){if(generation!==pollGeneration||current()?.card_id!==cardId)return;try{const job=await api('/api/v1/jobs/'+id);if(generation!==pollGeneration||current()?.card_id!==cardId)return;if(job.status==='failed')throw Error(job.error?.message||'Распознавание не выполнено');if(job.status==='succeeded'){const response=await api('/api/v1/cards/'+cardId+'/ocr-suggestions?job_id='+encodeURIComponent(id));if(generation!==pollGeneration||current()?.card_id!==cardId)return;result=response;loading=false;render();onAnalysis();return}loading=true;$('#hints-status').textContent='Ищем подсказки. Можно переключиться к карточке и продолжать ввод.';$('#start-ocr').disabled=true;timer=setTimeout(()=>poll(id,cardId,generation),1000)}catch(error){if(current()?.card_id===cardId&&generation===pollGeneration){loading=false;render();$('#hints-status').textContent=error.message+'. Введённые сведения не изменились.'}}}
 async function accept(row,fieldId,replace=false){
  if(!fieldId){notice('Выберите характеристику в списке «Куда вставить строку».');return}
  let accepted=false;
  try{await busy(async()=>{
   if(!await savePending())return;
   const base=current();
   const updated=await api('/api/v1/cards/'+base.card_id+'/accept-suggestion',json('POST',{expected_revision:base.revision,job_id:jobId,field_id:fieldId,source_ids:row.source_ids,replace_existing:replace}));
   skipped.add(key(row));persist();setCard(updated);extra.add(fieldId);renderCard();showWorkspace('editor');accepted=true;
   notice('Подсказка перенесена с источником. Проверьте значение и отметьте «Проверено».','success');
  })}catch(error){
   notice(error.message);
   if(error.code==='FIELD_HAS_VALUE'){
    const label=current().fields.find(f=>f.field_id===fieldId)?.label||config.labels[fieldId]||fieldId;
    const button=make('button','Заменить «'+label+'» этой подсказкой','secondary');button.type='button';button.onclick=()=>accept(row,fieldId,true);$('#notice').append(button);
   }
  }
  if(accepted){const target=$('#value-'+fieldId);target?.focus({preventScroll:true});target?.scrollIntoView({block:'center'})}
 }
 function render(){if(!current()||!config)return;const card=current();$('#active-ocr-mode').textContent='OCR — по запросу';$('#photo-count').textContent=card.photos.length+' фото';$('#manual-photo-count').textContent=card.photos.length+'/3';$('#photo-upload-note').textContent=card.photos.length===3?'Добавлено три фото.':'Добавление фото не запускает распознавание.';$('#files').disabled=card.photos.length>=3;const uploadControls=$('.photo-upload-controls');if(uploadControls&&uploadControls.dataset.card!==card.card_id+':'+card.photos.length){uploadControls.open=!card.photos.length;uploadControls.dataset.card=card.card_id+':'+card.photos.length}const strip=$('#manual-photo-strip');strip.replaceChildren();for(const photo of card.photos){const button=make('button','','manual-photo');button.type='button';button.setAttribute('aria-label','Открыть фото товара');const image=make('img');image.src=photo.url;image.alt='';image.width=80;image.height=80;button.append(image);button.onclick=()=>showSource(photo.photo_id);strip.append(button)}$('#start-ocr').disabled=loading||!card.photos.length;$('#start-ocr').textContent=loading?'Ищем сведения…':'Найти сведения на фото';$('#ocr-mode').disabled=loading;$('#card-ocr-provider').textContent=result?.analysis_card.ocr.provider||'Распознавание не запускалось для этих подсказок.';
  if(!result){renderInline();clearOCR();$('#ocr-text').replaceChildren();$('#copy-all-ocr').disabled=true;$('#ocr-copy-status').textContent='';$('#hints-status').textContent=loading?'Ищем подсказки. Можно продолжать заполнение карточки.':'Подсказки появятся только после запуска. Ничего не будет вставлено автоматически.';return}
  $('#hints-status').textContent='Выберите полезное. Принятие и пропуск работают с одной подсказкой; поля сами не изменяются.';
  renderOCR(result.analysis_card,{...config.labels,...Object.fromEntries(card.fields.map(f=>[f.field_id,f.label||config.labels[f.field_id]||f.field_id]))},{selectedFields:visibleFields(),api:async()=>result.review,photo:showSource,accept,skip:row=>{skipped.add(key(row));persist();render()},isSkipped:row=>skipped.has(key(row))});renderInline();
 }
 return {configure,start,create,open,abandon,render,visibleFields,applyFields};
}
