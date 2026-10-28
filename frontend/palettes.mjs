// Presentation preferences contain no product facts and never change a card revision.
export const palettes = [
  {id:'strata',name:'Strata',note:'Молочный · бирюзовый · розовый',colors:['#FAF2E9','#0A3235','#F0529C','#FFFFFF']},
  {id:'ocean',name:'Морская',note:'Белый · графит · синий',colors:['#F3F6FC','#182A43','#175CD3','#FFFFFF']},
  {id:'sage',name:'Шалфей',note:'Тёплый светлый · лесной зелёный',colors:['#F6F7F2','#24382E','#254F3D','#FFFEFA']},
  {id:'clay',name:'Терракота',note:'Песочный · чернильный · глиняный',colors:['#FAF5EF','#392C26','#9A462B','#FFFFFF']},
];
export function paletteId(value){return palettes.some(p=>p.id===value)?value:'strata'}
export function applyPalette(value){
  const id=paletteId(value);document.documentElement.dataset.palette=id;
  const meta=document.querySelector('meta[name="theme-color"]');if(meta)meta.content=palettes.find(p=>p.id===id).colors[0];
  try{localStorage.setItem('polka-palette',id)}catch{}
  document.dispatchEvent(new CustomEvent('polka:palette',{detail:id}));return id;
}
export function savedPalette(){try{return paletteId(localStorage.getItem('polka-palette'))}catch{return 'strata'}}
export function bindGalleries(root=document){
  root.querySelectorAll('.product-gallery').forEach(gallery=>{
    gallery.querySelectorAll('[data-photo-index]').forEach(button=>button.onclick=()=>{
      gallery.querySelectorAll('[data-photo-index]').forEach(b=>b.setAttribute('aria-pressed',String(b===button)));
      gallery.querySelectorAll('[data-product-photo]').forEach(photo=>photo.hidden=photo.dataset.productPhoto!==button.dataset.photoIndex);
    });
    gallery.querySelectorAll('.product-image img').forEach(img=>img.addEventListener('error',()=>{
      img.hidden=true;const message=document.createElement('p');message.className='product-note';message.textContent='Фото недоступно. Возможно, срок хранения истёк. Вернитесь в редактор.';img.after(message);
    },{once:true}));
  });
}
