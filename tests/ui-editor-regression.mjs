// Runs through the documented CUA tab API in Codex, on an isolated test origin.
// No external provider calls, mocks, browser globals or direct state mutation.
export async function runNameRegression(tab,{testOrigin}){
 if((await tab.url())!==testOrigin+'/')throw Error('Use an explicitly isolated test origin');
 const ui=tab.playwright;
 const expect=(value,message)=>{if(!value)throw Error(message)};
 const checks=[];
 await ui.getByRole('button',{name:'Новый товар',exact:true}).click();
 await ui.getByRole('heading',{name:'Черновик товара',exact:true,level:1}).waitFor({state:'visible',timeoutMs:15000});
 await ui.locator('#value-product_name').fill('Регрессионный тест: Футболка');
 let state=await ui.evaluate(()=>({pending:document.querySelector('#recommendation-status').innerText,
  issues:document.querySelector('#recommendations').innerText,required:document.querySelectorAll('.field-options,.required-toggle').length}));
 expect(state.pending.includes('несохранённые'),'Dirty state is not visible');
 expect(!state.issues.includes('Не заполнено: Название товара'),'Outdated missing-name issue is still visible');
 expect(state.required===0,'Optional-field requirement controls are still visible');
 checks.push('Dirty name hides stale moderation; no requirement controls');
 await ui.locator('#review-product_name').click();
 await ui.getByRole('heading',{name:'Регрессионный тест: Футболка',exact:true,level:1}).waitFor({state:'visible',timeoutMs:15000});
 await tab.reload();
 await ui.getByText('Замечания к сохранённым сведениям.',{exact:true}).waitFor({state:'visible',timeoutMs:15000});
 state=await ui.evaluate(()=>({name:document.querySelector('#value-product_name').value,
  reviewed:document.querySelector('#review-product_name').checked,issues:document.querySelector('#recommendations').innerText}));
 expect(state.name==='Регрессионный тест: Футболка'&&state.reviewed,'Checking the name did not persist');
 expect(!state.issues.includes('Название товара'),'Saved reviewed name still needs moderation');
 checks.push('Review checkbox persists the name and clears name issues after reload');
 await ui.locator('#description').fill('Свой текст продавца, который нужно сохранить.');
 expect(await ui.getByRole('button',{name:'Сохранить правки',exact:true}).isEnabled(),'Description-only save is disabled');
 await ui.getByRole('button',{name:'Сохранить правки',exact:true}).click();
 await ui.getByText('Все изменения сохранены',{exact:true}).waitFor({state:'visible',timeoutMs:15000});
 await tab.reload();
 await ui.getByText('Замечания к сохранённым сведениям.',{exact:true}).waitFor({state:'visible',timeoutMs:15000});
 state=await ui.evaluate(()=>({text:document.querySelector('#description').value}));
 expect(state.text==='Свой текст продавца, который нужно сохранить.','Save lost the seller description');
 await ui.getByRole('button',{name:'Проверил описание',exact:true}).click();
 await ui.getByText('Готова к подтверждению',{exact:true}).waitFor({state:'visible',timeoutMs:15000});
 checks.push('Description-only Save works; description review needs no second checkbox');
 return checks;
}

export async function runOCRRegression(tab,{testOrigin,resume=false}){
 if((await tab.url())!==testOrigin+'/')throw Error('Use an explicitly isolated test origin');
 const ui=tab.playwright,ready=()=>ui.locator('#operation-status').waitFor({state:'hidden',timeoutMs:15000});
 const check=(value,message)=>{if(!value)throw Error(message)};
 if(!resume){
 await ui.getByRole('searchbox',{name:'Добавить характеристику'}).fill('Примечание для теста');
 await ui.getByRole('button',{name:'Создать «Примечание для теста»',exact:true}).click();await ready();
 await ui.getByRole('button',{name:'Фото и подсказки',exact:true}).click();
 await ui.getByText('Тестовые фотографии',{exact:true}).click();
 await ui.getByRole('button',{name:'Кабель, EN',exact:true}).click();await ready();
 await ui.getByRole('button',{name:'Найти сведения на фото',exact:true}).click();
 return ['OCR started; inspect readiness and call again with resume:true'];
 }
 await ui.getByRole('button',{name:'Добавить «Бренд» и принять',exact:true}).waitFor({state:'visible',timeoutMs:60000});
 await ui.getByRole('button',{name:'Карточка товара',exact:true}).click();
 const draft='Несохранённый текст: сохранить после переноса OCR.';
 await ui.getByRole('textbox',{name:'Описание товара',exact:true}).fill(draft);
 await ui.getByRole('button',{name:'Фото и подсказки',exact:true}).click();
 await ui.getByRole('button',{name:'Добавить «Бренд» и принять',exact:true}).click();await ready();
 let state=await ui.evaluate(()=>({brand:document.querySelector('#value-brand')?.value,description:document.querySelector('#description').value}));
 check(state.brand==='Example'&&state.description===draft,'Known OCR acceptance lost a field or unsaved prose');
 await ui.getByRole('button',{name:'Фото и подсказки',exact:true}).click();
 await ui.getByLabel('Куда вставить строку',{exact:true}).selectOption({label:'Примечание для теста'});
 await ui.getByText('Прочий текст · 1',{exact:true}).click();
 await ui.getByRole('button',{name:'Принять в «Примечание для теста»',exact:true}).click();await ready();
 state=await ui.evaluate(()=>({custom:document.querySelector('[name^="custom_"]')?.value,description:document.querySelector('#description').value,nameReviewed:document.querySelector('#review-product_name').checked}));
 check(state.custom.includes('СИНТЕТИЧЕСКАЯ')&&state.description===draft&&state.nameReviewed,'Raw OCR transfer changed the name, target or draft');
 return ['Known OCR row added with its source; unsaved description preserved','Unclassified OCR row transferred to selected custom field; reviewed name preserved'];
}
