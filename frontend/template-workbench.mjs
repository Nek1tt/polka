import {palettes,applyPalette,savedPalette,bindGalleries} from './palettes.mjs';
const make=(tag,className,text)=>{const n=document.createElement(tag);if(className)n.className=className;if(text)n.textContent=text;return n};
const designs={market_v1:['Витрина','Галерея слева, сведения в центре, проверка справа.'],studio_v1:['Акцент на фото','Крупное изображение и спокойная подача деталей.'],compact_v1:['Каталог','Компактная галерея, характеристики на первом плане.']};
export function createWorkbench(getState,selectTemplate){
  const grid=document.querySelector('#palette-options');
  for(const p of palettes){
    const label=make('label','palette-choice'),radio=make('input');radio.type='radio';radio.name='palette';radio.value=p.id;radio.setAttribute('aria-label',p.name);radio.checked=p.id===savedPalette();
    const swatches=make('span','palette-swatches');swatches.setAttribute('aria-hidden','true');
    for(const color of p.colors){const swatch=make('span');swatch.style.background=color;swatches.append(swatch)}
    const copy=make('span','palette-copy');copy.append(make('strong','',p.name),make('small','',p.note));
    label.append(radio,swatches,copy);grid.append(label);radio.onchange=()=>applyPalette(p.id);
  }
  document.addEventListener('polka:palette',event=>{
    grid.querySelectorAll('input').forEach(radio=>radio.checked=radio.value===event.detail);
  });
  applyPalette(savedPalette());
  const button=document.querySelector('#generate-variants'),status=document.querySelector('#variants-status'),results=document.querySelector('#variant-results'),tiles=document.querySelector('#variant-options'),stage=document.querySelector('#variant-stage');
  let generation=0,key='',views=new Map(),busy=false;
  function sync(){
    const {card,unsaved,selected}=getState();
    const next=card?`${card.card_id}@${card.revision}`:'';
    if(next!==key){generation++;key=next;views.clear();results.hidden=true;stage.replaceChildren();tiles.replaceChildren();busy=false}
    button.disabled=!card||unsaved||busy;
    button.textContent=busy?'Собираем варианты…':views.size?'Обновить варианты':'Создать 3 варианта';
    if(unsaved){generation++;busy=false;views.clear();results.hidden=true;status.textContent='Сохраните правки, чтобы создать варианты.'}
    else if(!busy)status.textContent=views.size?`Выберите оформление ниже.`:'Сравните три варианта с одинаковыми сведениями о товаре.';
    if(selected&&views.has(selected.template_id)){results.hidden=false;show(selected.template_id)}
    else if(views.size)results.hidden=true;
  }
  function show(id){
    if(!views.has(id))return;
    stage.replaceChildren(views.get(id).cloneNode(true));bindGalleries(stage);
    tiles.querySelectorAll('button').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.template===id)));
    document.querySelector('#chosen-template-name').textContent=designs[id]?.[0]||id;
  }
  button.onclick=async()=>{
    const {card,unsaved,templates}=getState();if(!card||unsaved)return;
    const id=card.card_id,revision=card.revision,request=++generation;
    const choices=templates.filter(t=>designs[t.template_id]&&(t.supported_categories.includes('*')||t.supported_categories.includes(card.category.selected)));
    if(choices.length!==3){status.textContent='Не удалось получить три шаблона. Проверьте доступность сервера и обновите страницу.';return}
    busy=true;button.disabled=true;button.textContent='Собираем варианты…';status.textContent='Собираем три оформления из сохранённых сведений…';
    const current=()=>{const s=getState();return request===generation&&s.card?.card_id===id&&s.card.revision===revision&&!s.unsaved};
    try{
      const pages=await Promise.all(choices.map(async t=>{
        const query=new URLSearchParams({template_id:t.template_id,template_version:t.version,expected_revision:revision});
        const response=await fetch(`/api/v1/cards/${encodeURIComponent(id)}/preview.html?${query}`);
        if(!response.ok){const error=await response.json().catch(()=>({}));throw Error(error.error?.message||'Не удалось загрузить вариант. Повторите попытку.')}
        const doc=new DOMParser().parseFromString(await response.text(),'text/html'),surface=doc.querySelector('.product-preview');
        if(!surface)throw Error('Сервер вернул старый формат предпросмотра. Перезапустите обновлённый проект.');
        return [t.template_id,surface];
      }));
      if(!current())return;
      views=new Map(pages);tiles.replaceChildren();
      for(const t of choices){
        const b=make('button','variant-tile');b.type='button';b.dataset.template=t.template_id;b.setAttribute('aria-pressed','false');
        const thumb=make('span',`variant-wire wire-${t.template_id}`);thumb.setAttribute('aria-hidden','true');
        const photo=make('span','wire-photo'),name=make('span','wire-content'),review=make('span','wire-review');
        // Only an actual private photo and the actual title are used in the choice tile.
        if(card.photos[0]){const img=make('img');img.src='/api/v1/photos/'+encodeURIComponent(card.photos[0].photo_id);img.alt='';img.width=90;img.height=100;photo.append(img)}
        name.append(make('strong','',card.fields.find(f=>f.field_id==='product_name')?.value||'Название не указано'),make('span','wire-line'),make('span','wire-line'));
        review.append(make('span','',`${card.readiness.required_filled}/${card.readiness.required_total}`));thumb.append(photo,name,review);
        b.append(thumb,make('strong','variant-name',designs[t.template_id][0]),make('span','variant-note',designs[t.template_id][1]));
        b.onclick=()=>{selectTemplate(t);show(t.template_id)};tiles.append(b);
      }
      results.hidden=false;selectTemplate(choices[0]);show(choices[0].template_id);
      status.textContent=`Готово: три оформления ревизии ${revision}. Факты и статусы проверки сохранены.`;
      document.querySelector('#variant-results-title').focus({preventScroll:true});results.scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth',block:'start'});
    }catch(error){if(current())status.textContent=error.message}
    finally{if(request===generation){busy=false;button.disabled=false;button.textContent=views.size?'Обновить варианты':'Повторить создание вариантов'}}
  };
  return {sync};
}
