"""Build a private, reversible bilingual localisation mod from installed files. MIT."""
import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
try:
    from .stellaris_library import ENTRY, detect_game
except ImportError:
    from stellaris_library import ENTRY, detect_game

TITLE='Alex English + Chinese · 双语学习界面'
FOLDER='alex_bilingual_learning'


def read_localisations(root):
    languages={'english':{},'simp_chinese':{}};counts={};skipped=0
    files=sorted((root/'localisation').rglob('*.yml'),key=lambda p:('replace' in p.parts,str(p).lower()))
    for p in files:
        if not p.resolve().is_relative_to(root.resolve()) or p.stat().st_size>20*1024*1024:continue
        raw=p.read_text(encoding='utf-8-sig',errors='replace')
        head=re.search(r'^\s*l_(english|simp_chinese)\s*:',raw,re.M)
        if not head:continue
        language=head[1];counts[language]=counts.get(language,0)+1
        for line in raw.splitlines():
            m=ENTRY.match(line)
            if m:languages[language][m[1]]=re.sub(r'\\([ntr"\\])',lambda x:{'n':'\n','t':'\t','r':'\r','"':'"','\\':'\\'}[x[1]],m[2])
            elif line.strip() and not line.lstrip().startswith(('#','l_')):skipped+=1
    return languages,counts,skipped


def alias(key,language):return 'ALEXBL_'+language+'_'+hashlib.sha256(key.encode()).hexdigest()[:20]


def rewrite(value,entries,language):
    return re.sub(r'\$([^$|]+)(\|[^$]*)?\$',lambda m:'$'+alias(m[1],language)+(m[2] or '')+'$' if m[1] in entries else m[0],value)


def quote(value):return value.replace('\\','\\\\').replace('"','\\"').replace('\r','\\r').replace('\n','\\n').replace('\t','\\t')


def bilingual_value(key,english,chinese):
    en=english[key];zh=chinese.get(key,'')
    # Formatting fragments and variable-only strings retain their original behaviour.
    visible=re.sub(r'\$[^$]*\$|\[[^\]]*\]|£[^£]*£|§.', '',en)
    if not re.search('[A-Za-z]{2}',visible) or not re.search('[\u3400-\u9fff]',zh) or en==zh:return None
    left='$'+alias(key,'E')+'$';right='$'+alias(key,'C')+'$'
    long=len(visible)>65 or '\n' in en or '\n' in zh or len(zh)>45
    return left+'\n'+right if long else left+'（'+right+'）'


def active_sources(documents):
    load=documents/'dlc_load.json'
    if not load.exists():return []
    result=[]
    for name in json.loads(load.read_text(encoding='utf-8-sig')).get('enabled_mods',[]):
        descriptor=documents/name
        if not descriptor.resolve().is_relative_to((documents/'mod').resolve()) or not descriptor.is_file():continue
        raw=descriptor.read_text(encoding='utf-8-sig');path=re.search(r'^\s*path\s*=\s*"([^"]+)"',raw,re.M)
        if not path:continue
        root=Path(path[1]);root=root if root.is_absolute() else documents/root
        if root.name==FOLDER or not (root/'localisation').is_dir():continue
        title=re.search(r'^\s*name\s*=\s*"([^"]+)"',raw,re.M)
        result.append((root,title[1] if title else root.name))
    return result


def build(game,documents,output,include_mods=True):
    if not (game/'localisation/english').is_dir():raise ValueError('请选择有效的群星安装目录。')
    en={};zh={};sources=[];skipped=0
    roots=[(game,'Stellaris')]+(active_sources(documents) if include_mods else [])
    for root,title in roots:
        texts,counts,ignored=read_localisations(root);en.update(texts['english']);zh.update(texts['simp_chinese']);skipped+=ignored
        sources.append({'name':title,'files':counts})
    if not en or not zh:raise ValueError('未找到中英文文件。')
    output.mkdir(parents=True,exist_ok=True)
    combined={key:value for key in en if (value:=bilingual_value(key,en,zh)) is not None}
    # Private aliases prevent English references resolving to already bilingual labels.
    rows=[(alias(k,'E'),rewrite(v,en,'E')) for k,v in en.items()]
    rows.extend((alias(k,'C'),rewrite(v,zh,'C')) for k,v in zh.items())
    rows.extend(combined.items())
    for lang in ('english','simp_chinese'):
        target=output/'localisation/replace'/lang;target.mkdir(parents=True,exist_ok=True)
        # One stable filename avoids stale generated chunks after a game update.
        p=target/('zz_alex_bilingual_l_'+lang+'.yml')
        temporary=p.with_suffix('.yml.pending')
        with temporary.open('w',encoding='utf-8-sig',newline='\n') as f:
            f.write('l_'+lang+':\n')
            for key,value in rows:f.write(' '+key+':0 "'+quote(value)+'"\n')
        os.replace(temporary,p)
    # Reuse installed Chinese glyphs when the game remains in English.
    original=game/'interface/fonts.gfx'
    if original.exists():
        font=original.read_text(encoding='utf-8-sig')
        font,count=re.subn(r'languages\s*=\s*\{\s*"l_simp_chinese"\s*\}', 'languages = { "l_simp_chinese" "l_english" }',font)
        if not count:raise ValueError('当前版本的中文字体定义未识别，暂不安装。')
        (output/'interface').mkdir(exist_ok=True);(output/'interface/fonts.gfx').write_text(font,encoding='utf-8-sig')
    else:raise ValueError('未找到游戏字体定义。')
    info=json.loads((game/'launcher-settings.json').read_text(encoding='utf-8-sig'))
    supported=info.get('modsCompatibilityVersion','4.*').lstrip('v')+'.*'
    descriptor='version="1.0"\nname="'+TITLE+'"\ntags={ "Translation" }\nsupported_version="'+supported+'"\n'
    (output/'descriptor.mod').write_text(descriptor,encoding='utf-8')
    documents.joinpath('mod').mkdir(exist_ok=True)
    pointer=documents/'mod'/('alex_bilingual_learning.mod')
    pointer.write_text(descriptor+'path="'+output.resolve().as_posix()+'"\n',encoding='utf-8')
    report={'bilingual_entries':len(combined),'english_entries':len(en),'chinese_entries':len(zh),'generated_entries_per_language':len(rows),'sources':sources,'skipped_lines':skipped,'installed':datetime.now().isoformat(timespec='seconds'),'game_version':info.get('version'),'requires_launcher_enable':True,'game_ui_tested':False}
    (output/'build-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return report


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--game');parser.add_argument('--documents');parser.add_argument('--base-only',action='store_true');args=parser.parse_args()
    found=detect_game();game=Path(args.game or (found[0] if len(found)==1 else ''))
    documents=Path(args.documents) if args.documents else Path.home()/'Documents/Paradox Interactive/Stellaris'
    if not documents.is_dir():raise ValueError('没有找到群星用户目录，请指定 --documents。')
    result=build(game.resolve(),documents,documents/'mod'/FOLDER,not args.base_only)
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
