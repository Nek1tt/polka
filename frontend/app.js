import {currentRecommendations} from './editor-state.mjs';
import {createAttributeBuilder} from './attribute-builder.mjs';
import {createTextAssistance} from './text-assistance.mjs';
import {createProductLibrary} from './product-library.mjs';
import {createManualEditor} from './manual-editor.mjs';
import {createWorkbench} from './template-workbench.mjs';
import {compatibleTemplates,chooseTemplate,previewUrl} from './editor-projection.mjs';
const $=s=>document.querySelector(s), el=(tag,attrs={},text='')=>{const n=document.createElement(tag);Object.entries(attrs).forEach(([k,v])=>k==='class'?n.className=v:n.setAttribute(k,v));n.textContent=text;return n};
let files=[],card=null,config=null,dirty=new Set(),categoryDirty=false,descriptionDirty=false,timer=null,started=Date.now(),currentPhoto=null;
let templates=[],catalogError='',recommendationsRequest=0,manualSupported=false;

let workspaceCardId=null,workspaceMode='editor';
function showWorkspace(mode){
 workspaceMode=mode==='editor'?'editor':'analysis';
 $('.workspace-grid').dataset.workspaceView=workspaceMode;$('#workspace').dataset.workspaceView=workspaceMode;
 $('#analysis-view').hidden=workspaceMode!=='analysis';
 $('#editor-view').hidden=workspaceMode!=='editor';$('#review-view').hidden=workspaceMode!=='editor';
 $('#analysis-view-button').setAttribute('aria-pressed',String(workspaceMode==='analysis'));
 $('#editor-view-button').setAttribute('aria-pressed',String(workspaceMode==='editor'));
}
function showSource(id,bbox=null){showWorkspace('analysis');photo(id,bbox);(bbox?$('#bbox'):$('#photo-stage')).scrollIntoView({behavior:'smooth',block:bbox?'center':'start'})}
function focusField(id){showWorkspace('editor');const target=id==='description'?$('#description'):id==='category'?$('#category'):$('#value-'+id);if(!target)return;for(let parent=target.parentElement;parent;parent=parent.parentElement)if(parent.tagName==='DETAILS')parent.open=true;target.scrollIntoView({behavior:'smooth',block:'center'});target.focus({preventScroll:true})}
$('#analysis-view-button').onclick=()=>showWorkspace('analysis');
$('#editor-view-button').onclick=()=>showWorkspace('editor');
$('.variant-results-head>a').addEventListener('click',()=>showWorkspace('editor'));

function notice(text,tone='warning'){
 const target=$('#notice');target.replaceChildren();target.hidden=!text;target.dataset.kind=tone;
 if(text){target.append(el('span',{},text));const close=el('button',{type:'button',class:'notice-close','aria-label':'Закрыть сообщение'},'×');close.onclick=()=>{target.hidden=true};target.append(close)}
}
function pendingReview(){
 $('#save-fields').disabled=false;$('#dirty-label').textContent=dirty.size?'Есть несохранённые правки':'Описание ещё не сохранено';$('#workspace-save-state').textContent=dirty.size?'Есть несохранённые правки':'Описание ещё не сохранено';
 recommendationsRequest++;$('#recommendations').replaceChildren();$('#recommendation-count').textContent='—';$('#retry-recommendations').hidden=true;
 $('#recommendation-status').textContent='Есть несохранённые изменения. Сохраните их, чтобы обновить проверку.';
 $('#issues').hidden=true;$('#moderation-pending').hidden=false;$('#issue-count').textContent='—';$('#photo-analysis-status').hidden=true;
 $('#readiness-number').textContent='—';$('#readiness-state').textContent='Проверка после сохранения';$('#readiness-help').textContent='Замечания обновятся после сохранения текущих правок.';
 $('#progress-bar').style.width='0%';$('#save-review-changes').hidden=false;$('#confirm').disabled=true;
}

async function api(url,options={}){const r=await fetch(url,options);if(!r.ok){let e=await r.json().catch(()=>({}));const error=Error(e.error?.message||`Ошибка ${r.status}`);error.code=e.error?.code;throw error}return r.json()}
function json(method,data){return {method,headers:{'Content-Type':'application/json'},body:JSON.stringify(data)}}
function view(){$('#products-library').hidden=true;$('.steps').hidden=false;document.body.dataset.view='workspace'; $('#workspace').hidden=false;$('#app-loading').hidden=true;$('#step1').classList.toggle('active',card?.readiness.state==='needs_information');$('#step2').classList.toggle('active',['needs_review','ready_to_confirm'].includes(card?.readiness.state));$('#step3').classList.toggle('active',card?.readiness.state==='confirmed') }
function photo(id,bbox=null){const p=card.photos.find(p=>p.photo_id===id);if(!p)return;currentPhoto=id;$('#source-photo').width=p.width;$('#source-photo').height=p.height;$('#source-photo').src=p.url;$('#open-source-photo').href=p.url;$('#source-photo').hidden=false;$('#photo-empty').hidden=true;$('#open-source-photo').hidden=false;$('#bbox').hidden=!bbox;if(bbox){const n=$('#bbox');n.style.left=(bbox[0]*100)+'%';n.style.top=(bbox[1]*100)+'%';n.style.width=((bbox[2]-bbox[0])*100)+'%';n.style.height=((bbox[3]-bbox[1])*100)+'%'}}
function sourceButton(sid){const s=card.sources.find(s=>s.source_id===sid);const b=el('button',{class:'source-link',type:'button'},s?.kind==='ocr_text'?'На фото':s?.kind==='classifier'?'Правило':'Введено вами');b.onclick=()=>{if(s?.photo_id){showSource(s.photo_id,s.bbox)}else notice(`Исходные сведения: ${s?.text||''}`)};return b}
function markDirty(key){dirty.add(key);$('#workspace-save-state').textContent='Есть несохранённые правки';$('#dirty-label').textContent='Есть несохранённые правки';$('#save-fields').disabled=false;$('#confirm').disabled=true;$('#export').hidden=true;$('#text-export').hidden=true;refreshPreviewLink()}
function renderCard(){$('#issues').hidden=false;$('#moderation-pending').hidden=true;$('#save-review-changes').hidden=true;view('workspace');$('#workspace').classList.toggle('has-product-name',!!card.fields.find(f=>f.field_id==='product_name').value);if(workspaceCardId!==card.card_id){workspaceCardId=card.card_id;workspaceMode='editor'}showWorkspace(workspaceMode);$('#workspace-save-state').textContent='';descriptionDirty=false;dirty.clear();categoryDirty=false;$('#save-fields').disabled=true;$('#dirty-label').textContent='Все изменения сохранены';$('#card-id').textContent=`Карточка ${card.card_id.slice(0,8)}, ревизия ${card.revision}`;$('#card-title').textContent=card.fields.find(f=>f.field_id==='product_name').value||'Черновик товара';$('#photo-count').textContent=card.photos.length+' фото';$('#photo-tabs').replaceChildren();for(const [i,p] of card.photos.entries()){const b=el('button',{class:'photo-tab'},'Фото '+(i+1));b.onclick=()=>photo(p.photo_id);$('#photo-tabs').append(b)}if(card.photos.length)photo(currentPhoto&&card.photos.some(p=>p.photo_id===currentPhoto)?currentPhoto:card.photos[0].photo_id);else{$('#source-photo').hidden=true;$('#bbox').hidden=true;$('#photo-empty').hidden=false;$('#open-source-photo').hidden=true}
 manual.render();
 const cat=$('#category-editor');cat.replaceChildren();const cd=el('div',{class:'field'}),ch=el('div',{class:'field-heading'});ch.append(el('label',{for:'category'},'Тип товара (необязательно)'));const check=el('label',{class:'check'});check.innerHTML='<input type="checkbox" id="category-reviewed"> Проверено';ch.append(check);cd.append(ch);const select=el('input',{id:'category',maxlength:'200',placeholder:'Например, настольная лампа'});select.value=card.category.selected==='unknown'?'':card.category.selected;cd.append(select);cat.append(cd);$('#category-reviewed').checked=card.category.reviewed;select.oninput=()=>{categoryDirty=true;$('#category-reviewed').checked=false;markDirty('category')};$('#category-reviewed').onchange=async()=>{categoryDirty=true;markDirty('category');await savePending({focusId:'category-reviewed'})};
 const target=$('#fields-editor');target.replaceChildren();const extra=el('details',{class:'extra-fields'});extra.append(el('summary',{},'Дополнительные поля'));target.append(extra);for(const f of card.fields){const d=el('div',{class:'field',id:'field-'+f.field_id});const head=el('div',{class:'field-heading'});head.append(el('label',{for:'value-'+f.field_id},(f.label||config.labels[f.field_id]||f.field_id)+(f.required?' *':'')));const ck=el('label',{class:'check'}),cb=el('input',{type:'checkbox',id:'review-'+f.field_id});cb.checked=f.reviewed;cb.onchange=async()=>{if(cb.checked&&!input.value.trim()){cb.checked=false;notice('Сначала заполните характеристику, затем отметьте её проверенной.');return}markDirty(f.field_id);await savePending({focusId:cb.id})};ck.append(cb,document.createTextNode('Проверено'));head.append(ck);const input=el(['ingredients','storage_conditions','specifications'].includes(f.field_id)?'textarea':'input',{rows:'3',id:'value-'+f.field_id,name:f.field_id,autocomplete:'off',placeholder:f.required?'Нужно уточнить':'Добавьте, если известно',maxlength:'4000'});input.value=f.value||'';input.oninput=()=>{cb.checked=false;meta.replaceChildren(el('span',{},'Ваш текст, ещё не сохранён'));markDirty(f.field_id)};d.append(head,input);const meta=el('div',{class:'field-meta'});f.source_ids.forEach(s=>meta.append(sourceButton(s)));if(!f.value)meta.append(el('span',{},'Нет данных'));d.append(meta);if(f.status==='conflict'){const box=el('div',{class:'conflict'});box.append(el('strong',{},'Противоречие источников'));for(const candidate of f.candidates){const p=el('p',{},candidate.value+' · ');candidate.source_ids.forEach(s=>p.append(sourceButton(s)));box.append(p)}const resolved=el('label',{class:'check'});const rc=el('input',{type:'checkbox',id:'resolve-'+f.field_id});rc.onchange=()=>markDirty(f.field_id);resolved.append(rc,document.createTextNode('Разрешить противоречие: выбранное выше значение верно'));box.append(resolved);d.append(box)}if(f.value||f.required||manual.visibleFields().includes(f.field_id))target.insertBefore(d,extra);else extra.append(d)}
 manual.applyFields();attributes.render();$('#description').value=card.description.text;$('#description-assert').checked=card.description.mode==='user';$('#description-mode').textContent=card.description.mode==='template'?'Из принятых фактов':card.description.mode==='llm'?'Предложено LLM':'Внесено пользователем';$('#description-sources').textContent=card.description.reviewed?'✓ Проверено пользователем':'Требует проверки';
 const r=card.readiness;$('#editor-status').textContent=r.state==='confirmed'?'Подтверждено':'Черновик';$('#readiness-help').textContent=r.state==='confirmed'?'Подтверждена текущая ревизия. Изменение сведений потребует новой проверки.':'Заполненные сведения нужно проверить перед подтверждением.';$('#readiness-number').innerHTML=`${r.required_filled}<span>/ ${r.required_total}</span>`;$('#progress-bar').style.width=(r.required_filled/r.required_total*100)+'%';const states={needs_information:'Нужно добавить сведения',needs_review:'Нужна ваша проверка',ready_to_confirm:'Готова к подтверждению',confirmed:'✓ Подтверждено вами'};$('#readiness-state').textContent=states[r.state];$('#confirm').disabled=r.state!=='ready_to_confirm';$('#confirm').hidden=r.state==='confirmed';$('#export').hidden=r.state!=='confirmed';$('#export').href='/api/v1/cards/'+card.card_id+'/export';$('#text-export').hidden=r.state!=='confirmed';$('#export-text').href='/api/v1/cards/'+card.card_id+'/export?format=text';$('#issue-count').textContent=card.issues.length;const issues=$('#issues');issues.replaceChildren();for(const issue of card.issues){const d=el('div',{class:'issue '+issue.severity});d.append(el('strong',{},issue.message),el('p',{},issue.suggestion));if(issue.field_ids.length){const go=()=>{focusField(issue.field_ids[0])};const action=el('button',{class:'source-link',type:'button'},'Перейти к проверке');action.onclick=go;d.append(action)}issues.append(d)}if(!card.issues.length)issues.append(el('p',{class:'small success'},'Блокирующих замечаний нет.'));renderEditorTools();}
function restoreDescriptionDraft(draft){
 if(!draft)return;
 $('#description').value=draft.text;$('#description-assert').checked=draft.asserted;
 $('#description').setSelectionRange(draft.start??0,draft.end??0);
 descriptionDirty=true;
 $('#description-mode').textContent='Редактируется';
 $('#description-sources').textContent='Есть несохранённые правки описания';
 $('#workspace-save-state').textContent='Описание ещё не сохранено';
 $('#dirty-label').textContent=dirty.size?'Есть несохранённые правки':'Характеристики сохранены. Описание ещё не сохранено';
 $('#confirm').disabled=true;$('#export').hidden=true;$('#text-export').hidden=true;refreshPreviewLink();
}
async function change(payload){return busy(async()=>{notice('');const draft=descriptionDirty&&!payload.description_update?{text:$('#description').value,asserted:$('#description-assert').checked,start:$('#description').selectionStart,end:$('#description').selectionEnd}:null;try{card=await api('/api/v1/cards/'+card.card_id,json('PATCH',{expected_revision:card.revision,...payload}));renderCard();restoreDescriptionDraft(draft);return true}catch(e){notice(e.message+' Ваши несохранённые правки остались в форме.');if(e.code==='REVISION_CONFLICT'){const b=el('button',{class:'secondary'},'Обновить ревизию, сохранив мои правки');b.onclick=async()=>{try{const edits=[...dirty].filter(k=>k!=='category').map(k=>({key:k,value:$('#value-'+k).value,reviewed:$('#review-'+k).checked,resolve:$('#resolve-'+k)?.checked||false}));const cat=categoryDirty?{value:$('#category').value,reviewed:$('#category-reviewed').checked}:null;const description=descriptionDirty||payload.description_update?{text:$('#description').value,asserted:$('#description-assert').checked}:null;card=await api('/api/v1/cards/'+card.card_id);renderCard();for(const edit of edits){const input=$('#value-'+edit.key);if(!input)continue;input.value=edit.value;$('#review-'+edit.key).checked=edit.reviewed;if($('#resolve-'+edit.key))$('#resolve-'+edit.key).checked=edit.resolve;markDirty(edit.key)}if(cat){$('#category').value=cat.value;$('#category-reviewed').checked=cat.reviewed;categoryDirty=true;markDirty('category')}restoreDescriptionDraft(description);refreshPreviewLink();notice('Ревизия обновлена. Сверьте восстановленные правки с источниками и сохраните повторно.')}catch(error){notice(error.message)}};$('#notice').append(document.createElement('br'),b)}return false}})}
async function savePending({description=false,focusId=null}={}){
 const payload={field_updates:pendingFields()};
 if(categoryDirty)payload.category_update={selected:$('#category').value.trim()||'unknown',reviewed:$('#category-reviewed').checked};
 if(description&&descriptionDirty)payload.description_update={text:$('#description').value,reviewed:false,asserted_as_user_input:$('#description-assert').checked};
 if(!payload.field_updates.length&&!payload.category_update&&!payload.description_update)return true;
 const saved=await change(payload);if(saved&&focusId)$('#'+focusId)?.focus({preventScroll:true});return saved;
}
$('#save-fields').onclick=()=>savePending({description:true});
$('#save-review-changes').onclick=()=>savePending({description:true});
$('#review-description').onclick=async()=>{
 const before=$('#description').value,wasDirty=descriptionDirty;
 if(!await savePending())return;
 if(!wasDirty&&before!==$('#description').value){notice('Характеристики сохранены, описание обновилось. Прочитайте новый текст и нажмите «Проверил описание».');return}
 await change({description_update:{text:$('#description').value,reviewed:true,asserted_as_user_input:$('#description-assert').checked}});
};
$('#description').oninput=()=>{$('#description-assert').checked=true;descriptionDirty=true;$('#description-mode').textContent='Редактируется';$('#description-sources').textContent='Есть несохранённые правки описания';$('#confirm').disabled=true;$('#export').hidden=true;$('#text-export').hidden=true;refreshPreviewLink()};
async function regenerate(){
 if(!await savePending())return;
 await busy(async()=>{try{card=await api('/api/v1/cards/'+card.card_id+'/description-template',json('POST',{expected_revision:card.revision}));renderCard();notice('Описание собрано из проверенных характеристик. Прочитайте его перед подтверждением.','success')}catch(error){notice(error.message)}});
}
$('#regenerate').onclick=()=>{if(!descriptionDirty)return regenerate();notice('В описании есть несохранённый текст. Заменить его описанием из проверенных характеристик?');const replace=el('button',{type:'button',class:'secondary'},'Заменить описание');replace.onclick=regenerate;$('#notice').append(replace)};
$('#confirm').onclick=async()=>{if(dirty.size||$('#description').value!==card.description.text){notice('Сохраните и проверьте текущие правки перед подтверждением.');return}try{card=await api('/api/v1/cards/'+card.card_id+'/confirm',json('POST',{expected_revision:card.revision}));renderCard();notice(`Подтверждена ревизия ${card.revision}. Можно скопировать текст или скачать описание. Время этого сеанса: ${Math.round((Date.now()-started)/1000)} с.`,'success')}catch(e){notice(e.message)}};
$('#new-card').onclick=async()=>{if(dirty.size||descriptionDirty){notice('Сохраните текущие правки перед созданием новой карточки.');return}await manual.create()} ;
window.addEventListener('beforeunload',e=>{if(dirty.size||descriptionDirty){e.preventDefault();e.returnValue=''}});
async function loadEditorCatalog(){
 const results=await Promise.allSettled([api('/api/v1/templates'),api('/api/v1/version')]);
 if(results[0].status==='fulfilled'){templates=results[0].value.templates;catalogError=''}
 else{templates=[];catalogError='Шаблоны недоступны. Перезапустите обновлённый сервер и обновите страницу.'}
 manualSupported=results[1].status==='fulfilled'&&results[1].value.features.product_library===true&&results[1].value.features.attribute_builder===true&&results[1].value.features.reliable_editor===true;
 $('#app-version').textContent=results[1].status==='fulfilled'?`API ${results[1].value.api_version}`:'Версия API недоступна';
}
function templatePreference(){try{return JSON.parse(localStorage.getItem('polka-template-'+card.card_id)||'null')}catch{return null}}
function renderEditorTools(){
 const select=$('#card-template');select.replaceChildren();
 const choices=compatibleTemplates(templates,card.category.selected);
 const chosen=chooseTemplate(templates,card.category.selected,templatePreference());
 for(const t of choices)select.append(el('option',{value:`${t.template_id}@${t.version}`},t.name));
 if(chosen)select.value=`${chosen.template_id}@${chosen.version}`;
 else select.append(el('option',{},'Шаблоны недоступны'));
 select.disabled=!chosen;refreshPreviewLink();loadRecommendations();
}
function refreshPreviewLink(){
 if(!card)return;
 const selected=templates.find(t=>`${t.template_id}@${t.version}`===$('#card-template').value);
 const unsaved=dirty.size>0||descriptionDirty;
 let url=previewUrl(card,selected,unsaved);if(url)url+='&palette='+encodeURIComponent(document.documentElement.dataset.palette||'strata');const link=$('#preview-card');
 if(url){link.href=url;link.removeAttribute('aria-disabled');link.removeAttribute('tabindex');link.style.opacity=''}
 else{link.removeAttribute('href');link.setAttribute('aria-disabled','true');link.setAttribute('tabindex','-1');link.style.opacity='.45'}
 $('#template-note').textContent=unsaved?'Сначала сохраните правки характеристик и проверьте изменённое описание.':
   catalogError||(selected?`Предпросмотр сохранённой ревизии ${card.revision}. Все шаблоны подходят для любых товаров.`:'Шаблоны временно недоступны.');
 workbench.sync();textAssistance.sync();if(dirty.size||descriptionDirty)pendingReview();
}
$('#card-template').onchange=()=>{
 const selected=templates.find(t=>`${t.template_id}@${t.version}`===$('#card-template').value);
 if(selected&&card){try{localStorage.setItem('polka-template-'+card.card_id,JSON.stringify({template_id:selected.template_id,version:selected.version}))}catch{}}
 refreshPreviewLink();
};
$('#preview-card').onclick=e=>{if($('#preview-card').getAttribute('aria-disabled')==='true'){e.preventDefault();notice('Предпросмотр недоступен: сохраните текущие правки или проверьте доступность шаблонов.')}};
async function loadRecommendations(){
 if(!card)return;if(dirty.size||descriptionDirty){pendingReview();return}
 $('#photo-analysis-status').hidden=true;
 const id=card.card_id,revision=card.revision,request=++recommendationsRequest;
 const current=()=>currentRecommendations({card,id,revision,request,latest:recommendationsRequest,dirty:dirty.size>0||descriptionDirty});
 $('#recommendation-status').textContent='Загружаем рекомендации…';$('#recommendations').replaceChildren();$('#recommendation-count').textContent='—';$('#retry-recommendations').hidden=true;
 try{
  const data=await api(`/api/v1/cards/${encodeURIComponent(id)}/recommendations?expected_revision=${revision}`);
  if(!current())return;
  $('#recommendation-count').textContent=data.recommendations.length;
  $('#recommendation-status').textContent=`Замечания к сохранённым сведениям.`;
  const analysis=data.photo_analysis;
  $('#photo-analysis-status').hidden=!analysis;
  $('#photo-analysis-status').textContent=analysis?'Оценка текста на фото: последний успешный запуск '+new Intl.DateTimeFormat('ru-RU',{dateStyle:'short',timeStyle:'short'}).format(new Date(analysis.requested_at))+'. Товарные сведения не изменены.':'';
  document.querySelectorAll('[data-photo-analysis-issue]').forEach(node=>node.remove());
  for(const issue of analysis?.issues||[]){const node=el('div',{class:'issue '+issue.severity,'data-photo-analysis-issue':''});node.append(el('strong',{},issue.message),el('p',{},issue.suggestion));const button=el('button',{class:'source-link',type:'button'},'Показать фотографию');button.onclick=()=>showSource(issue.photo_ids[0]);node.append(button);$('#issues').append(node)}
  $('#issue-count').textContent=card.issues.length+(analysis?.issues.length||0);
  for(const r of data.recommendations){
   const compact=r.rule_id==='unreviewed_value';
   const d=el('div',{class:'issue '+r.priority+(compact?' compact-review':'')});d.append(el('strong',{},r.reason));
   if(!compact)d.append(el('p',{},r.action));
   if(r.question&&!['review_value','review_description'].includes(r.action_type))d.append(el('p',{},r.question));
   for(const candidate of r.candidates||[]){const row=el('p',{},candidate.value+' · ');candidate.source_ids.forEach(sid=>row.append(sourceButton(sid)));d.append(row)}
   const fieldId=r.field_ids[0];
   if(fieldId){
    const button=el('button',{class:'secondary',type:'button'},fieldId==='description'?'Проверить описание':fieldId==='category'?'Проверить тип товара':'Перейти к полю');
    button.onclick=()=>{focusField(fieldId)};
    d.append(button);
   }
   if(r.rule_id==='missing_photos'){const button=el('button',{class:'secondary',type:'button'},'Добавить фото');button.onclick=()=>{showWorkspace('analysis');$('#drop').scrollIntoView({block:'center'});$('#files').focus()};d.append(button)}
   if(r.photo_ids.length){const button=el('button',{class:'secondary',type:'button'},'Показать фотографию');button.onclick=()=>{showSource(r.photo_ids[0])};d.append(button)}
   $('#recommendations').append(d);
  }
  if(!data.recommendations.length)$('#recommendation-status').textContent=`Для ревизии ${revision} дополнительных действий нет.`;
 }catch(e){if(!current())return;$('#recommendation-status').textContent=e.code==='REVISION_CONFLICT'?'Карточка изменилась в другой вкладке. Обновите её перед проверкой рекомендаций.':`Не удалось загрузить рекомендации: ${e.message}`;$('#retry-recommendations').hidden=false}
}
$('#retry-recommendations').onclick=loadRecommendations;
const workbench=createWorkbench(()=>({card,unsaved:dirty.size>0||descriptionDirty,templates,selected:templates.find(t=>`${t.template_id}@${t.version}`===$('#card-template').value)}),t=>{$('#card-template').value=`${t.template_id}@${t.version}`;$('#card-template').onchange()});
document.addEventListener('polka:palette',()=>{if(card)refreshPreviewLink()});
function renderManualCard(){
 const draft=descriptionDirty?{text:$('#description').value,asserted:$('#description-assert').checked,start:$('#description').selectionStart,end:$('#description').selectionEnd}:null;
 renderCard();restoreDescriptionDraft(draft);
}
const manual=createManualEditor({api,json,notice,busy,renderCard:renderManualCard,savePending,showWorkspace,showSource,onAnalysis:loadRecommendations,getState:()=>({card,dirty:dirty.size>0||descriptionDirty}),setCard:value=>{card=value;localStorage.setItem('polka-manual-card',value.card_id)}});
$('#review-all').onclick=async()=>{
 if(!card)return;
 const updates=card.fields.map(f=>({field_id:f.field_id,value:$('#value-'+f.field_id).value.trim()||null,reviewed:!!$('#value-'+f.field_id).value.trim()&&(f.status!=='conflict'||!!$('#resolve-'+f.field_id)?.checked),resolve_conflict:$('#resolve-'+f.field_id)?.checked||false}));
 const payload={field_updates:updates,category_update:{selected:$('#category').value.trim()||'unknown',reviewed:!!$('#category').value.trim()}};
 if(descriptionDirty)payload.description_update={text:$('#description').value,reviewed:true,asserted_as_user_input:$('#description-assert').checked};
 const asserted=$('#description-assert').checked||(!descriptionDirty&&card.description.statements.length>0&&card.description.statements.every(s=>s.asserted_as_user_input));
 await busy(async()=>{
  if(!await change(payload))return;
  if(card.description.text&&!await change({description_update:{text:card.description.text,reviewed:true,asserted_as_user_input:asserted}}))return;
  notice(card.readiness.state==='ready_to_confirm'?'Заполненные сведения и описание проверены и сохранены. Теперь можно подтвердить карточку.':'Заполненные сведения сохранены. Оставшиеся замечания показаны в проверке карточки.',card.readiness.state==='ready_to_confirm'?'success':'warning');
 });
};
$('#copy-product-text').onclick=async()=>{if(dirty.size||descriptionDirty){notice('Сохраните и подтвердите правки перед копированием.');return}try{const response=await fetch('/api/v1/cards/'+card.card_id+'/export?format=text');if(!response.ok)throw Error('Сначала подтвердите текущую ревизию карточки.');const text=await response.text();await navigator.clipboard.writeText(text);notice('Текст товара скопирован. Можно вставить его в магазин или документ.','success')}catch(error){notice(error.message+' Можно скачать описание файлом.')}};
const library=createProductLibrary({api,notice,json,getState:()=>({card,dirty:dirty.size>0||descriptionDirty}),open:id=>manual.open(id),create:()=>manual.create(),clear:()=>{manual.abandon();card=null;workspaceCardId=null;localStorage.removeItem('polka-manual-card')},back:()=>{view();showWorkspace(workspaceMode)}});
function pendingFields(excluded=[]){return [...dirty].filter(k=>k!=='category'&&!excluded.includes(k)).map(k=>({field_id:k,value:$('#value-'+k).value.trim()||null,reviewed:$('#review-'+k).checked,resolve_conflict:$('#resolve-'+k)?.checked||false}))}
const attributes=createAttributeBuilder({getState:()=>({card}),focus:focusField,change:payload=>change({...payload,field_updates:pendingFields(payload.remove_fields),...(categoryDirty?{category_update:{selected:$('#category').value.trim()||'unknown',reviewed:$('#category-reviewed').checked}}:{})})});
const textAssistance=createTextAssistance({getState:()=>({card,dirty:dirty.size>0||descriptionDirty}),api,json,notice,busy,renderCard,setCard:value=>{card=value}});
let busyDepth=0;async function busy(action){
 busyDepth++;$('#workspace').inert=true;$('#workspace').setAttribute('aria-busy','true');$('#operation-status').hidden=false;$('#open-products').disabled=true;
 try{return await action()}finally{busyDepth--;const active=busyDepth>0;$('#workspace').inert=active;$('#workspace').setAttribute('aria-busy',String(active));$('#operation-status').hidden=!active;$('#open-products').disabled=active}
}
(async()=>{try{config=await api('/api/v1/config');await loadEditorCatalog();if(!manualSupported)throw Error('Открыт прежний сервер. Ручному редактору нужен API 2.4.2: запустите обновлённый проект и откройте его адрес.');config.labels={...config.labels,...Object.fromEntries(config.attribute_catalog.map(f=>[f.field_id,f.label]))};attributes.configure(config);textAssistance.configure(config);manual.configure(config);await manual.start()}catch(error){$('#app-loading').textContent='Не удалось открыть редактор. Проверьте сервер и обновите страницу.';notice(error.message)}})();

// Non-modal appearance menu: close without changing the current selection.
const paletteMenu=$('.palette-panel');
document.addEventListener('keydown',event=>{if(event.key==='Escape'&&paletteMenu.open){paletteMenu.open=false;paletteMenu.querySelector('summary').focus()}});
document.addEventListener('click',event=>{if(!paletteMenu.contains(event.target))paletteMenu.open=false});
