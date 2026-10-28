// UI invariants shared by asynchronous recommendations and OCR controls.
export function chooseOCRTarget(ids, preferred){return ids.includes(preferred)?preferred:(ids[0]||'')}
export function currentRecommendations({card,id,revision,request,latest,dirty}){
 return !!card&&card.card_id===id&&card.revision===revision&&request===latest&&!dirty;
}
