// Presentation choice never changes facts, review flags or confirmation.
export function compatibleTemplates(templates, category) {
  return templates.filter(t => (t.supported_categories.includes('*') || t.supported_categories.includes(category)));
}
export function chooseTemplate(templates, category, preference) {
  const compatible = compatibleTemplates(templates, category);
  return compatible.find(t => t.template_id === preference?.template_id && t.version === preference.version)
    || compatible.find(t => t.template_id === 'market_v1')
    || compatible.find(t => t.template_id === `${category}_v1`)
    || compatible.find(t => t.template_id === 'universal_v1') || compatible[0] || null;
}
export function previewUrl(card, selected, hasUnsavedChanges) {
  if (!card || !selected || hasUnsavedChanges || !(selected.supported_categories.includes('*') || selected.supported_categories.includes(card.category.selected))) return null;
  const query = new URLSearchParams({template_id:selected.template_id,template_version:String(selected.version),expected_revision:String(card.revision)});
  return `/api/v1/cards/${encodeURIComponent(card.card_id)}/preview.html?${query}`;
}
