const $=s=>document.querySelector(s);
const node=(tag,text='',cls='')=>{const n=document.createElement(tag);n.textContent=text;n.className=cls;return n};
export function createTextAssistance({getState,api,json,setCard,renderCard,notice,busy}){
 let config=null,result=null,generation=0,running=false;
 function configure(value){config=value.llm;$('#llm-provider').textContent=config.available?`${config.provider} · ${config.model}`:'LLM не подключена. Для включения нужен серверный API-ключ.';$('#llm-notice').textContent=config.notice;sync()}
 function sync(){
  const {card,dirty}=getState();if(!config||!card)return;
  if(result&&(result.card_id!==card.card_id||result.card_revision!==card.revision)){result=null;$('#llm-results').replaceChildren()}
  $('#analyze-text').disabled=running||!config.available||dirty||!$('#llm-consent').checked;
  $('#analyze-text').textContent=running?'Анализируем текст…':'Проверить текст и предложить описание';
  $('#llm-state').textContent=running?'Запрос отправлен. Можно продолжать редактирование.':dirty?'Сохраните правки перед анализом.':result?'Предложение для сохранённой ревизии '+result.card_revision+'. Сверьте текст перед применением.':'';
  $('#apply-llm-description')?.toggleAttribute('disabled',dirty||running);
 }
 $('#llm-consent').onchange=sync;
 $('#analyze-text').onclick=async()=>{
  const {card,dirty}=getState();if(dirty||running||!config.available)return;
  const request=++generation;running=true;sync();$('#llm-results').replaceChildren();
  try{
   const response=await api(`/api/v1/cards/${card.card_id}/text-assistance`,json('POST',{expected_revision:card.revision,allow_external_processing:$('#llm-consent').checked}));
   const current=getState();if(request!==generation||current.card?.card_id!==card.card_id||current.card.revision!==card.revision)return;
   result=response;renderResult();
  }catch(error){if(getState().card?.card_id===card.card_id)notice(error.message)}finally{running=false;sync()}
 };
 function renderResult(){
  const target=$('#llm-results');target.replaceChildren();const data=result.result;
  if(data.description_sentences.length){
   target.append(node('h3','Предложение описания'),node('p',data.description_sentences.map(s=>s.text).join('\n'),'llm-proposal'));
   const details=node('details'),summary=node('summary','Какие сведения использовала модель');details.append(summary);
   const fields=getState().card.fields;
   for(const sentence of data.description_sentences){details.append(node('p',sentence.text,'small'),node('p',sentence.fact_ids.map(id=>{const f=fields.find(f=>f.field_id===id);return f?`${f.label||id}: ${f.value}`:'Текст продавца'}).join('; '),'small muted'))}target.append(details);
   const apply=node('button','Заменить описание этим вариантом','secondary');apply.id='apply-llm-description';apply.type='button';
   apply.onclick=async()=>{
    const state=getState();if(state.dirty||state.card.card_id!==result.card_id||state.card.revision!==result.card_revision){notice('Карточка изменилась. Сохраните правки и запустите новый анализ.');return}
    apply.disabled=true;const proposal=result;
    try{await busy(async()=>{const updated=await api(`/api/v1/cards/${proposal.card_id}/apply-text-assistance`,json('POST',{expected_revision:proposal.card_revision,analysis_id:proposal.analysis_id}));const current=getState();if(current.card?.card_id!==proposal.card_id||current.dirty)return;setCard(updated);renderCard();notice('Предложение перенесено в описание. Оно ещё не проверено: прочитайте и подтвердите текст.')})}catch(error){notice(error.message);apply.disabled=false}
   };target.append(apply);
  }
  target.append(node('h3','Замечания к тексту'));
  if(!data.recommendations.length)target.append(node('p','Модель не предложила замечаний. Это не гарантия отсутствия ошибок.','small'));
  for(const item of data.recommendations){const row=node('div','','llm-item');if(item.fragment)row.append(node('blockquote',item.fragment));row.append(node('p',item.message));target.append(row)}
  if(data.questions.length){target.append(node('h3','Что можно уточнить'));for(const item of data.questions)target.append(node('p',item.question,'llm-question'))}
 }
 return {configure,sync};
}
