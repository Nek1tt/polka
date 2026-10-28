const $=s=>document.querySelector(s);
const node=(tag,text='',cls='')=>{const n=document.createElement(tag);n.textContent=text;n.className=cls;return n};
export const selectedAttributes=card=>card.fields.filter(f=>f.label||f.value||f.required);
export function createAttributeBuilder({getState,change,focus}){
 let catalog=[];
 function configure(config){catalog=config.attribute_catalog;$('#attribute-search').oninput=search}
 function button(text,action){const b=node('button',text,'source-link');b.type='button';b.onclick=action;return b}
 function search(){
  const query=$('#attribute-search').value.trim(),target=$('#attribute-results'),card=getState().card;
  target.replaceChildren();if(!card)return;
  const selected=new Set(selectedAttributes(card).map(f=>f.field_id));
  const matches=catalog.filter(f=>!selected.has(f.field_id)&&f.label.toLocaleLowerCase('ru').includes(query.toLocaleLowerCase('ru')));
  for(const item of matches.slice(0,query?30:6))target.append(button('+ '+item.label,()=>add(item)));
  if(query&&!catalog.some(f=>f.label.toLocaleLowerCase('ru')===query.toLocaleLowerCase('ru'))&&!card.fields.some(f=>(f.label||f.field_id).toLocaleLowerCase('ru')===query.toLocaleLowerCase('ru')))
   target.append(button('Создать «'+query+'»',()=>add({label:query})));
  const alreadyAdded=query&&card.fields.some(f=>(f.label||f.field_id).toLocaleLowerCase('ru')===query.toLocaleLowerCase('ru'));
  $('#attribute-search-status').textContent=alreadyAdded?'Эта характеристика уже добавлена.':query?(matches.length?'Найдено: '+matches.length:'Можно создать свою характеристику.'):'Популярные характеристики. Введите название для поиска или создания своей.';
 }
 async function add(definition){
  const previous=new Set(getState().card.fields.map(f=>f.field_id));
  if(await change({add_fields:[definition]})){
   $('#attribute-search').value='';search();
   const added=getState().card.fields.find(f=>!previous.has(f.field_id))||getState().card.fields.find(f=>f.field_id===definition.field_id);if(added)focus(added.field_id);
  }
 }
 function render(){
  search();
  const unused=$('#fields-editor .extra-fields');if(unused)unused.hidden=true;
  for(const field of selectedAttributes(getState().card)){
   if(field.field_id==='product_name')continue;
   const target=$('#field-'+field.field_id),head=target?.querySelector('.field-heading');if(!head)continue;
   head.append(button('Убрать',()=>{
    if(target.querySelector('.remove-attribute'))return;
    const value=$('#value-'+field.field_id).value.trim();
    if(!value){change({remove_fields:[field.field_id]});return}
    const confirm=node('div','','remove-attribute');confirm.append(node('p','Убрать характеристику и её значение из карточки? Описание потребуется проверить заново.','small'));
    confirm.append(button('Убрать характеристику',()=>change({remove_fields:[field.field_id]})),button('Отмена',()=>confirm.remove()));target.append(confirm);
   }));
  }
 }
 return {configure,render};
}
