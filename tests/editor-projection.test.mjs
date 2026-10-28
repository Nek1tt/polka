import test from 'node:test';
import assert from 'node:assert/strict';
import {compatibleTemplates,chooseTemplate,previewUrl} from '../frontend/editor-projection.mjs';
const templates=[
 {template_id:'universal_v1',version:1,supported_categories:['dairy','jam','unknown']},
 {template_id:'dairy_v1',version:1,supported_categories:['dairy']},
 {template_id:'jam_v1',version:1,supported_categories:['jam']}
];
test('only compatible templates; explicit preference survives re-render',()=>{
 assert.equal(compatibleTemplates(templates,'unknown').length,1);
 assert.equal(chooseTemplate(templates,'dairy',null).template_id,'dairy_v1');
 assert.equal(chooseTemplate(templates,'dairy',{template_id:'universal_v1',version:1}).template_id,'universal_v1');
 assert.equal(chooseTemplate(templates,'jam',{template_id:'dairy_v1',version:1}).template_id,'jam_v1');
 assert.equal(chooseTemplate(templates,'jam',{template_id:'jam_v1',version:9}).version,1);
});
test('unsaved edits cannot open a stale preview; saved revision is exact and facts unchanged',()=>{
 const card={card_id:'example',revision:7,category:{selected:'dairy'},confirmation:{confirmed_revision:7}};
 const before=JSON.stringify(card),selected=templates[1];
 assert.equal(previewUrl(card,selected,true),null);
 assert.equal(previewUrl(card,templates[2],false),null);
 const url=previewUrl(card,selected,false);
 assert.match(url,/expected_revision=7/);assert.match(url,/template_version=1/);
 assert.equal(JSON.stringify(card),before);
});

test('v2 wildcard layouts work for arbitrary product types',()=>{
 const universal=[{template_id:'market_v1',version:1,supported_categories:['*']}];
 for(const category of ['unknown','USB cable','Одежда']){
  assert.equal(compatibleTemplates(universal,category).length,1);
  assert.ok(previewUrl({card_id:'c',revision:1,category:{selected:category}},universal[0],false));
 }
});
