const $=selector=>document.querySelector(selector);
const make=(tag,text='',className='')=>{const node=document.createElement(tag);node.textContent=text;node.className=className;return node};
const states={needs_information:'Нужно заполнить',needs_review:'Нужно проверить',ready_to_confirm:'Готов к подтверждению',confirmed:'Подтверждён'};
export function createProductLibrary({api,notice,getState,open,create,clear,back}){
 let generation=0;
 const guard=()=>{if(!getState().dirty)return true;notice('Сохраните текущие правки и проверьте изменённое описание перед сменой или удалением товара.');return false};
 async function load(){
  const request=++generation;
  $('#products-status').textContent='Загружаем товары…';$('#retry-products').hidden=true;$('#products-list').replaceChildren();
  try{
   const {cards}=await api('/api/v1/cards');if(request!==generation)return;
   $('#products-status').textContent=cards.length?'Сохранено товаров: '+cards.length:'Товаров пока нет. Создайте первый товар.';
   for(const item of cards){
    const row=make('article','','product-row'),thumb=make('div','','product-thumb'),body=make('div','','product-info'),actions=make('div','','product-actions');
    if(item.photo_url){const image=make('img');image.src=item.photo_url;image.alt='';image.width=72;image.height=88;image.loading='lazy';thumb.append(image)}else thumb.append(make('span','Без фото'));
    body.append(make('h2',item.title),make('p',states[item.state]||'Черновик','product-state'));
    const expiry=new Intl.DateTimeFormat('ru-RU',{day:'numeric',month:'short',hour:'2-digit',minute:'2-digit'}).format(new Date(item.expires_at));body.append(make('p','Доступен до '+expiry,'small muted'));
    const edit=make('button','Открыть','secondary'),remove=make('button','Удалить','source-link delete-product');edit.type=remove.type='button';
    edit.setAttribute('aria-label','Открыть товар «'+item.title+'»');remove.setAttribute('aria-label','Удалить товар «'+item.title+'»');
    edit.onclick=async()=>{if(!guard())return;row.inert=true;try{await open(item.card_id);generation++}catch(error){notice(error.message)}finally{row.inert=false}};
    const confirmation=make('div','','delete-confirmation');confirmation.hidden=true;
    const yes=make('button','Удалить товар','danger-button'),no=make('button','Отмена','secondary');yes.type=no.type='button';
    confirmation.append(make('p','Удалить «'+item.title+'» вместе с фотографиями и подсказками? Отменить удаление нельзя.'),yes,no);
    remove.onclick=()=>{confirmation.hidden=false;remove.hidden=true;no.focus()};
    const cancel=()=>{confirmation.hidden=true;remove.hidden=false;remove.focus()};no.onclick=cancel;confirmation.onkeydown=event=>{if(event.key==='Escape')cancel()};
    yes.onclick=async()=>{if(!guard())return;row.inert=true;try{await api('/api/v1/cards/'+item.card_id+'?expected_revision='+item.revision,{method:'DELETE'});if(getState().card?.card_id===item.card_id){clear();$('#return-to-card').hidden=true}for(const prefix of ['polka-hints-','polka-template-'])localStorage.removeItem(prefix+item.card_id);notice('Товар удалён.','success');await load()}catch(error){notice(error.message);row.inert=false;no.focus()}};
    actions.append(edit,remove);row.append(thumb,body,actions,confirmation);$('#products-list').append(row);
   }
  }catch(error){if(request!==generation)return;$('#products-status').textContent='Не удалось загрузить товары: '+error.message;$('#retry-products').hidden=false}
 }
 function show(){notice('');$('#workspace').hidden=true;$('.steps').hidden=true;$('#products-library').hidden=false;$('#return-to-card').hidden=!getState().card;$('#products-title').focus();load()}
 $('#open-products').onclick=show;$('#retry-products').onclick=load;
 $('#return-to-card').onclick=()=>{generation++;back()};
 $('#library-new-card').onclick=async()=>{if(!guard())return;$('#library-new-card').disabled=true;try{await create();generation++}catch(error){notice(error.message)}finally{$('#library-new-card').disabled=false}};
 return {show};
}
