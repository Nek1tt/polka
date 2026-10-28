"""Universal layouts: field references, no category restrictions or product defaults."""
from copy import deepcopy
from .domain import LABELS, REQUIRED
CATEGORY_LABELS={'unknown':'Любой товар'}
def block(block_id,title,kind='fields',field_ids=()):
    return dict(block_id=block_id,title=title,kind=kind,field_ids=list(field_ids))
_CATALOG={}
for tid,name in [('universal_v1','Универсальная карточка'),('market_v1','Витрина'),('studio_v1','Акцент на фото'),('compact_v1','Каталог')]:
    _CATALOG[(tid,1)]=dict(template_id=tid,version=1,name=name,supported_categories=['*'],description_styles=['structured'],blocks=[block('gallery','Фотографии товара','photos'),block('title','Название товара',field_ids=['product_name']),block('category','Тип товара (необязательно)','category'),block('characteristics','О товаре',field_ids=[k for k in LABELS if k!='product_name']),block('description','Описание','description')])
class CatalogError(Exception):
    def __init__(self,code,message,status=404): self.code,self.message,self.status=code,message,status
def list_templates(): return deepcopy(list(_CATALOG.values()))
def get_template(template_id,version):
    if not any(k[0]==template_id for k in _CATALOG): raise CatalogError('TEMPLATE_NOT_FOUND','Шаблон не найден')
    if (template_id,version) not in _CATALOG: raise CatalogError('TEMPLATE_VERSION_NOT_FOUND','Версия шаблона не найдена')
    return deepcopy(_CATALOG[(template_id,version)])
def category_profile(category):
    return dict(category=category,label=CATEGORY_LABELS.get(category,category),supported=True,fields=[dict(field_id=k,label=v,required=k in REQUIRED) for k,v in LABELS.items()])
