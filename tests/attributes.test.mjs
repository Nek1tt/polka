import test from 'node:test';
import assert from 'node:assert/strict';
import {selectedAttributes} from '../frontend/attribute-builder.mjs';
test('legacy empty defaults stay hidden; selected, filled and required fields stay visible',()=>{
 const card={fields:[
  {field_id:'product_name',required:true,value:null},
  {field_id:'fat_percent',required:false,value:null},
  {field_id:'brand',required:false,value:'Бренд продавца'},
  {field_id:'material',required:false,value:null,label:'Материал'},
  {field_id:'custom_size',required:true,value:null,label:'Размер рукоятки'}]};
 assert.deepEqual(selectedAttributes(card).map(f=>f.field_id),['product_name','brand','material','custom_size']);
 assert.equal(card.fields.length,5,'visibility must not delete historical data');
});
