"""Assemble actual cached Blender pixels with timed screenplay subtitles."""
import argparse
from collections import OrderedDict
import json
from pathlib import Path
import time
import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from studio_config import load_config


def timestamp(seconds):
    ms=round(seconds*1000);hours,ms=divmod(ms,3600000);minutes,ms=divmod(ms,60000);sec,ms=divmod(ms,1000)
    return f'{hours:02d}:{minutes:02d}:{sec:02d},{ms:03d}'


def wrap(draw,text,font,width):
    lines=[];current=''
    for character in text:
        if current and draw.textlength(current+character,font=font)>width:
            lines.append(current);current=character
        else:current+=character
    if current:lines.append(current)
    return lines


def encode_episode(output,episode_id):
    output=Path(output);config=load_config();series=json.loads((output/'series_plan.json').read_text())
    episode=next(e for e in series['episodes'] if e['id']==episode_id)
    screenplay=json.loads((output/f'{episode_id}_script.json').read_text())
    names={c['id']:c['name'] for c in series['characters']};colors={'A':'#ffc987','B':'#b5e6a8','C':'#a7d7ff'}
    font=ImageFont.truetype(str(config['font_path']),19);small=ImageFont.truetype(str(config['font_path']),15)
    file=output/f'{episode_id}.pending.mp4';writer=cv2.VideoWriter(str(file),cv2.VideoWriter_fourcc(*'avc1'),24,(640,480))
    assert writer.isOpened()
    cache=OrderedDict();composites=OrderedDict();frame_count=0;subtitles=[];time_offset=0;started=time.monotonic()
    for outline,script in zip(episode['scenes'],screenplay['scenes']):
        frames=json.loads((output/'scenes'/outline['id']/'frames.json').read_text())
        assert frames['frame_count']==outline['duration_s']*24
        dialogue=script['dialogue'];line_index=0
        for i,key in enumerate(frames['frame_keys']):
            t=i/24
            while line_index<len(dialogue) and dialogue[line_index]['end_s']<=t:line_index+=1
            line=dialogue[line_index] if line_index<len(dialogue) and dialogue[line_index]['start_s']<=t<dialogue[line_index]['end_s'] else None
            composite_key=(key,line_index if line is not None else -1,outline['id'])
            if composite_key in composites:
                frame=composites[composite_key];composites.move_to_end(composite_key)
            else:
                if key not in cache:
                    image=Image.open(output/'pixel_cache'/(key+'.png')).convert('RGB')
                    assert image.size==(640,360)
                    cache[key]=image.copy()
                    if len(cache)>48:cache.popitem(last=False)
                image=cache[key];canvas=Image.new('RGB',(640,480),'#15231d');canvas.paste(image,(0,0));draw=ImageDraw.Draw(canvas)
                draw.text((12,365),f'{series["title"]} · {episode_id.upper()} {episode["title"]} · {outline["id"]}',font=small,fill='#b7c9bd')
                if line:
                    speaker=line['speaker'];draw.text((12,389),names[speaker]+'：',font=small,fill=colors[speaker])
                    lines=wrap(draw,line['text'],font,614)
                    assert len(lines)<=3,(outline['id'],len(lines))
                    for j,text in enumerate(lines):draw.text((12,410+j*22),text,font=font,fill='#f1f4ef')
                frame=cv2.cvtColor(np.asarray(canvas),cv2.COLOR_RGB2BGR);composites[composite_key]=frame
                if len(composites)>64:composites.popitem(last=False)
            writer.write(frame);frame_count+=1
        for line in dialogue:
            subtitles.append(f'{len(subtitles)+1}\n{timestamp(time_offset+line["start_s"])} --> {timestamp(time_offset+line["end_s"])}\n{names[line["speaker"]]}：{line["text"]}\n')
        time_offset+=outline['duration_s']
    writer.release();assert frame_count==11520 and time_offset==480
    cap=cv2.VideoCapture(str(file));decoded=0;max_pts_error=0.
    while True:
        ok,frame=cap.read()
        if not ok:break
        max_pts_error=max(max_pts_error,abs(cap.get(cv2.CAP_PROP_POS_MSEC)/1000-decoded/24));decoded+=1
    fps=cap.get(cv2.CAP_PROP_FPS);cap.release()
    assert decoded==11520 and fps==24 and max_pts_error<.002,(decoded,fps,max_pts_error)
    file.replace(output/f'{episode_id}.mp4')
    (output/f'{episode_id}.srt').write_text('\n'.join(subtitles))
    report={'episode':episode_id,'frames_encoded':frame_count,'frames_decoded':decoded,'fps':fps,'duration_s':480,
            'max_pts_error_s':max_pts_error,'seconds':time.monotonic()-started,
            'source':'Actual Blender pixel-cache frames + script-timed subtitles; no duplicate scenes or time stretching; no audio track'}
    (output/f'{episode_id}_video_checks.json').write_text(json.dumps(report,indent=2))
    print('EPISODE_VIDEO_COMPLETE',json.dumps(report),flush=True)
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True);parser.add_argument('--episode',required=True)
    args=parser.parse_args();encode_episode(args.output,args.episode)
