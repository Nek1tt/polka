// Engineering utility for choosing a segmentation pass, not a probability.
const letters=s=>(s.match(/[A-Za-zА-Яа-яЁё]/g)||[]).length;
function metrics(tsv){
  let good=0,bad=0,short=0,total=0;
  for(const line of tsv.split('\n')){
    const c=line.split('\t');if(c[0]!=='5'||!c[11]?.trim())continue;
    const text=c[11].trim(),n=letters(text),confidence=Number(c[10]);total++;
    if(n>=3&&confidence>=60&&!(/[A-Za-z]/.test(text)&&/[А-Яа-яЁё]/.test(text)))good+=n;
    else if(confidence<45)bad+=Math.max(1,n);
    if(n<3&&!/\d/.test(text))short++;
  }
  return {utility:good-.5*bad-2*short,good,bad,short,total};
}
function needsFallback(data){const m=metrics(data.tsv);return m.good<15||m.bad>m.good*.6||m.short>m.total*.25}
function choose(primary,secondary){return metrics(secondary.tsv).utility>metrics(primary.tsv).utility?secondary:primary}
module.exports={metrics,needsFallback,choose};
