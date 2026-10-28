const test=require('node:test'),assert=require('node:assert/strict');
const {metrics,choose,needsFallback}=require('../ocr-selection.cjs');
const tsv=words=>words.map(([text,confidence],i)=>`5\t1\t1\t1\t1\t${i+1}\t0\t0\t10\t10\t${confidence}\t${text}`).join('\n');
test('a pile of weak fragments cannot beat a smaller readable result',()=>{
 const clean={tsv:tsv([['Product:',95],['Cable',94],['Brand:',92],['Example',96]])};
 const noise={tsv:tsv(Array.from({length:80},()=>['amt',20]))};
 assert.equal(choose(clean,noise),clean);assert.equal(needsFallback(clean),false);assert.equal(needsFallback(noise),true);
});
test('ties preserve primary observations without merging conflicting passes',()=>{
 const a={tsv:tsv([['Example',90]])},b={...a};assert.equal(choose(a,b),a);assert.ok(Number.isFinite(metrics(a.tsv).utility));
});
