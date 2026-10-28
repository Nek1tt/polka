import {chooseOCRTarget} from './editor-state.mjs';
const $=s=>document.querySelector(s);
let generation=0;
function node(tag,text,className=''){const n=document.createElement(tag);n.textContent=text;n.className=className;return n}
export async function copyText(text,status){
  try {await navigator.clipboard.writeText(text);status.textContent='Скопировано. Вставьте в нужное поле и проверьте.'}
  catch {const area=node('textarea',text);area.readOnly=true;area.setAttribute('aria-label','Текст для копирования');status.replaceChildren(node('span','Нажмите Ctrl+C (на телефоне — удерживайте выделение).'),area);area.focus();area.select()}
}
export function clearOCR(){generation++}
export async function renderOCR(card,labels,{photo,insert,api,accept,skip,isSkipped=()=>false,selectedFields=null}){
  const request=++generation,target=$('#ocr-text'),select=$('#ocr-target-field'),status=$('#ocr-copy-status'),copy=$('#copy-all-ocr');
  const chosen=select.value;select.replaceChildren();
  for(const [key,label] of Object.entries(labels).filter(([id])=>!selectedFields||selectedFields.includes(id))){const o=node('option',label);o.value=key;select.append(o)}
  select.value=chooseOCRTarget([...select.options].map(o=>o.value),chosen);
  select.onchange=()=>target.querySelectorAll('[data-target-field]').forEach(button=>button.textContent='Принять в «'+(labels[select.value]||'выбранное поле')+'»');
  const raw=card.sources.filter(s=>s.kind==='ocr_text'&&s.confidence?.kind==='ocr_aggregate');
  target.replaceChildren();status.textContent='Отбираем полезные фрагменты…';copy.disabled=true;copy.textContent='Скопировать полезное';
  function button(label,action){const b=node('button',label,'source-link');b.type='button';b.onclick=action;return b}
  function row(s){
    const item=node('div','','ocr-row'),text=node('p',s.text,'ocr-selectable'),actions=node('div','','ocr-actions');
    item.append(text);
    if(!s.field_id)item.append(node('p',s.reason,'small muted'));
    actions.append(button('На фото',()=>photo(s.photo_id,s.bbox)),button('Копировать',()=>copyText(s.text,status)));
    if(accept){const transfer=button(s.field_id?(selectedFields&&!selectedFields.includes(s.field_id)?'Добавить «'+labels[s.field_id]+'» и принять':'Принять в «'+labels[s.field_id]+'»'):'Принять в «'+(labels[select.value]||'выбранное поле')+'»',()=>accept(s,s.field_id||select.value));if(!s.field_id)transfer.dataset.targetField='';actions.append(transfer,button('Пропустить',()=>skip(s)))}
    else if(!s.field_id)actions.append(button('Вставить',()=>insert(select.value,s.text)));
    if(s.field_id&&!accept)actions.append(button(`В «${labels[s.field_id]}»`,()=>insert(s.field_id,s.suggested_value||s.text)));
    item.append(actions);return item;
  }
  function section(title,lines,open=false){
    if(!lines.length)return;
    const details=node('details','','ocr-group');details.open=open;details.append(node('summary',`${title} · ${lines.length}`));
    const list=node('div','','ocr-group-list');let rendered=0;
    function append(){for(const s of lines.slice(rendered,rendered+8))list.append(row(s));rendered=Math.min(rendered+8,lines.length);more.hidden=rendered===lines.length}
    const more=button('Показать все строки',()=>{for(const s of lines.slice(rendered))list.append(row(s));rendered=lines.length;more.hidden=true}),copyGroup=button('Скопировать раздел',()=>copyText(lines.map(s=>s.text).join('\n'),status));
    if(open)append();else details.addEventListener('toggle',()=>{if(details.open&&!rendered)append()});
    if(!open)details.append(copyGroup);details.append(list,more);target.append(details);
  }
  function rawSection(){
    if(!raw.length)return;
    const details=node('details','','ocr-group ocr-raw');details.append(node('summary',`Исходный OCR без отбора · ${raw.length} строк`));
    const rawText=raw.map(s=>s.text).join('\n'),area=node('pre',rawText,'ocr-raw-text');area.setAttribute('aria-label','Исходный OCR без отбора');
    details.append(node('p','Может содержать повторы и ошибки. Сохранён для ручной проверки.','small muted'),button('Копировать исходный текст',()=>copyText(rawText,status)),area);target.append(details);
  }
  try {
    const data=await api(`/api/v1/cards/${card.card_id}/ocr-review?expected_revision=${card.revision}`);
    if(request!==generation)return;
    target.append(node('p',`Найдено ${data.counts.raw} строк: полезных ${data.counts.useful}, прочих ${data.counts.other}, сомнительных ${data.counts.doubtful}, повторов ${data.counts.duplicates}.`,'small ocr-counts'));
    const useful=data.lines.filter(s=>s.group==='useful');
    copy.disabled=!useful.length;copy.onclick=()=>copyText(useful.map(s=>s.text).join('\n'),status);
    if(!useful.length)target.append(node('p','Надёжных фрагментов для карточки не найдено. Откройте прочий текст или добавьте крупное фото нужной надписи.','small'));
    section('Для карточки — проверьте',useful.filter(s=>!isSkipped(s)),true);
    for(const text of data.warnings)target.append(node('p',text,'ocr-warning small'));
    section('Прочий текст',data.lines.filter(s=>s.group==='other'&&!isSkipped(s)));
    // Broken fragments do not get individual actions; they are only in raw diagnostics.
    rawSection();status.textContent='Полезные строки нужно проверить. Полный текст доступен ниже.';
  }catch(error){
    if(request!==generation)return;
    status.textContent=`Отбор недоступен: ${error.message}. Проверьте обновление сервера и повторите.`;
    target.append(button('Повторить отбор',()=>renderOCR(card,labels,{photo,insert,api,accept,skip,isSkipped,selectedFields})));rawSection();
  }
}
