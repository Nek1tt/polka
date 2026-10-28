// Explicit download at setup/build time; inference never sends photos externally.
const fs = require('node:fs'); const path = require('node:path'); const crypto=require('node:crypto');
(async()=>{
 const cache=process.env.OCR_CACHE || path.join(__dirname,'model-cache'); fs.mkdirSync(cache,{recursive:true});
 const hashes={};
 const expected={rus:'63a48ae166be2bb9862839b6f75e11afbac5e3be5bd5fa9a155ea43d5cdf9575',eng:'ed350f3752f81ee8f38769edc14d92d997dababe23b565c59879372cc46a2468'};
 for(const lang of ['rus','eng']) {
  const url=`https://tessdata.projectnaptha.com/4.0.0/${lang}.traineddata.gz`;
  const target=path.join(cache,`${lang}.traineddata.gz`);
  if(fs.existsSync(target)&&crypto.createHash('sha256').update(fs.readFileSync(target)).digest('hex')===expected[lang]){
   hashes[lang]={url,sha256:expected[lang]};continue;
  }
  const r=await fetch(url); if(!r.ok) throw Error(`${lang}: HTTP ${r.status}`);
  const b=Buffer.from(await r.arrayBuffer()); const hash=crypto.createHash('sha256').update(b).digest('hex');
  if(hash!==expected[lang]) throw Error(`Unexpected SHA256 for ${lang}; model not saved.`);
  fs.writeFileSync(path.join(cache,`${lang}.traineddata.gz`),b);
  hashes[lang]={url,sha256:hash};
 }
 fs.writeFileSync(path.join(cache,'manifest.json'),JSON.stringify(hashes,null,2));
 console.log('Verified Russian and English OCR weights; manifest.json contains SHA256.');
})().catch(e=>{console.error(e.message);process.exit(1)});
