import test from 'node:test';
import assert from 'node:assert/strict';
import {chooseOCRTarget,currentRecommendations} from '../frontend/editor-state.mjs';

test('removing the selected characteristic cannot leave OCR with an empty target',()=>{
 assert.equal(chooseOCRTarget(['product_name','material'],'brand'),'product_name');
 assert.equal(chooseOCRTarget(['product_name','material'],'material'),'material');
 assert.equal(chooseOCRTarget(['product_name'],''),'product_name');
 assert.equal(chooseOCRTarget([], 'deleted'), '');
});

test('a recommendation response for saved data cannot replace the dirty editor state',()=>{
 const request={card:{card_id:'a',revision:7},id:'a',revision:7,request:1,latest:1,dirty:false};
 assert.equal(currentRecommendations(request),true);
 assert.equal(currentRecommendations({...request,dirty:true}),false);
 assert.equal(currentRecommendations({...request,latest:2}),false);
 assert.equal(currentRecommendations({...request,card:{card_id:'a',revision:8}}),false);
 assert.equal(currentRecommendations({...request,card:{card_id:'b',revision:7}}),false);
 assert.equal(currentRecommendations({...request,card:null}),false);
});
