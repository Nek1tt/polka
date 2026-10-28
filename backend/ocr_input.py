"""Small local OCR working copies; originals and normalized bbox stay intact."""
from pathlib import Path
from PIL import Image

def prepare_inputs(paths,folder):
    Path(folder).mkdir(parents=True,exist_ok=True)
    prepared=[];sizes=[]
    for i,path in enumerate(paths):
        with Image.open(path) as image:
            # Enlarge small print for Tesseract; never claim recovered detail.
            factor=min(3,1200/max(image.size)) if max(image.size)<900 else min(1,2400/max(image.size))
            if factor!=1:
                size=(round(image.width*factor),round(image.height*factor))
                target=Path(folder)/f'{i}.png'
                image.resize(size,Image.Resampling.LANCZOS).save(target)
                prepared.append(target);sizes.append(size)
            else: prepared.append(path);sizes.append(image.size)
    return prepared,sizes
