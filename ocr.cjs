// Isolated CPU OCR process. Python kills the process on timeout.
const {createWorker} = require('tesseract.js');
const path = require('node:path');
const fs = require('node:fs');
const {needsFallback,choose}=require('./ocr-selection.cjs');
(async () => {
  const cache = process.env.OCR_CACHE || path.join(__dirname, 'model-cache');
  fs.mkdirSync(cache, {recursive:true});
  const worker = await createWorker('rus+eng', 1, {cachePath:cache, langPath:cache, gzip:true});
  if (process.argv[2] === '--check') {
    await worker.terminate(); console.log(JSON.stringify({ready:true, provider:'Tesseract.js 6.0.1 / Tesseract WASM'})); return;
  }
  const results=[];
  for (const file of process.argv.slice(2)) {
    await worker.setParameters({tessedit_pageseg_mode:'3'});
    let {data} = await worker.recognize(file, {}, {text:true, tsv:true});
    let psm=3;
    if (needsFallback(data)) {
      await worker.setParameters({tessedit_pageseg_mode:'11'});
      const fallback=await worker.recognize(file, {}, {text:true, tsv:true});
      const selected=choose(data,fallback.data);
      if(selected===fallback.data){data=selected;psm=11;}
    }
    results.push({text:data.text, tsv:data.tsv, psm});
  }
  await worker.terminate();
  console.log(JSON.stringify(results));
})().catch(e => {console.error(e.message); process.exit(1)});
