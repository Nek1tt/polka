"""Explicit RU/EN headings; no semantic guesses or category restriction."""
import re
HEADINGS={
 'product_name':r'Название(?: товара)?|Наименование|Product(?: name)?|Name',
 'net_quantity':r'Масса(?: нетто)?|Вес(?: нетто)?|Объ[её]м|Количество|Net (?:weight|volume|quantity)|Volume|Quantity',
 'brand':r'Бренд|Торговая марка|Brand', 'model':r'Модель|Артикул|Model|SKU|Part number',
 'material':r'Материал|Material', 'dimensions':r'Размеры?|Dimensions|Size', 'color':r'Цвет|Colou?r',
 'specifications':r'Характеристики|Specifications|Features',
 'ingredients':r'Состав|Ingredients', 'storage_conditions':r'Условия хранения|Хранение|Хранить|Storage(?: conditions)?|Store',
 'shelf_life':r'Срок годности|Shelf life|Best before|Expiry date',
 'manufacturer':r'Производитель|Изготовитель|Manufacturer|Manufactured by', 'fat_percent':r'Жирность|Массовая доля жира|Fat content',
}
def classify_line(text):
    for key,heading in HEADINGS.items():
        match=re.fullmatch(r'\s*(?:'+heading+r')\s*[:：]\s*(\S.*)',text,re.I)
        if match: return key,match.group(1).strip()
    match=re.fullmatch(r'\s*[℮e]?\s*(\d+(?:[.,]\d+)?\s*(?:кг|г|мл|л|kg|g|ml|l|шт\.?|pcs))\s*',text,re.I)
    if match: return 'net_quantity',match.group(1)
    return None,None
