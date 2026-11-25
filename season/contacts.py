"""Contact sheets from actual representative camera pixels, for human review."""
import argparse
import json
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from studio_config import load_config


def contacts(output):
    output=Path(output);config=load_config();font=ImageFont.truetype(str(config['font_path']),17)
    for ep in range(1,6):
        episode=f'ep{ep:02d}';cards=[]
        for directory in sorted((output/'scenes').glob(episode+'*')):
            path=directory/'frames.json'
            if not path.exists():continue
            frames=json.loads(path.read_text())['representative_frames']
            for frame in frames:
                image=Image.open(frame['file']).convert('RGB').resize((480,270))
                card=Image.new('RGB',(480,302),'#e5ece1');card.paste(image,(0,32))
                ImageDraw.Draw(card).text((8,5),frame['shot'],font=font,fill='#21372b');cards.append(card)
        if not cards:continue
        columns=3;rows=(len(cards)+columns-1)//columns
        sheet=Image.new('RGB',(480*columns,302*rows),'#e5ece1')
        for i,card in enumerate(cards):sheet.paste(card,((i%columns)*480,(i//columns)*302))
        sheet.save(output/f'{episode}_contacts.jpg',quality=90)
        print(episode,len(cards),'actual camera views')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',required=True);args=p.parse_args();contacts(args.output)
