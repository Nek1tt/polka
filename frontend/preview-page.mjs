import {applyPalette,paletteId,bindGalleries} from './palettes.mjs';
const select=document.querySelector('#preview-palette');
select.value=paletteId(new URLSearchParams(location.search).get('palette'));
applyPalette(select.value);
select.onchange=()=>{applyPalette(select.value);const url=new URL(location.href);url.searchParams.set('palette',select.value);history.replaceState(null,'',url)};
bindGalleries();
