"""Legendas ASS com área segura e destaque por palavra, sem dependências externas."""
import html
import json
import math
from pathlib import Path
import re
import textwrap


def clean(text):
    text = html.unescape(re.sub(r'<[^>]*>', '', text))
    return ' '.join(re.sub(r'[{}\\]', '', text).split())


def seconds(value):
    hours, minutes, tail = value.replace(',', '.').split(':')
    return int(hours) * 3600 + int(minutes) * 60 + float(tail)


def ass_time(value):
    centiseconds = max(0, round(value * 100))
    hours, rest = divmod(centiseconds, 360000)
    minutes, rest = divmod(rest, 6000)
    secs, cs = divmod(rest, 100)
    return f'{hours}:{minutes:02}:{secs:02}.{cs:02}'


def read_srt(path, duration):
    cues = []
    raw = Path(path).read_text(encoding='utf-8-sig').replace('\r\n', '\n')
    for block in re.split(r'\n\s*\n', raw.strip()):
        match = re.search(r'(\d+:\d{2}:\d{2}[,.]\d{3})\s*-->\s*(\d+:\d{2}:\d{2}[,.]\d{3})[^\n]*\n([\s\S]+)', block)
        if not match:
            continue
        start, end = max(0, seconds(match[1])), min(duration, seconds(match[2]))
        text = clean(match[3])
        if text and end > start:
            cues.append(dict(start=start, end=end, text=text))
    if not cues:
        raise ValueError('SRT sem legendas válidas dentro do trecho escolhido.')
    return cues


def create_ass(srt, target, width, height, duration, style='discreta', words_file=None):
    cues = read_srt(srt, duration)
    timings = json.loads(Path(words_file).read_text()) if words_file and Path(words_file).exists() else []
    factor = width / 1080
    size = (72 if style == 'destaque' else 64) * factor
    line_limit = 24 if style == 'destaque' else 28
    header = (
        f'[Script Info]\nScriptType: v4.00+\nPlayResX: {width}\nPlayResY: {height}\nWrapStyle: 2\nScaledBorderAndShadow: yes\n\n'
        '[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n'
        f'Style: Default,Montserrat,{size},&H00FFFFFF,&H0018C5F5,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,{3*factor},0,2,{int(90*factor)},{int(90*factor)},{int(360*factor)},1\n\n'
        '[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n'
    )
    events = []
    for cue in cues:
        matched = [w for w in timings if w['start'] >= cue['start'] - 0.02 and w['end'] <= cue['end'] + 0.02 and clean(w['text'])]
        if not matched:
            # SRT não tem tempos por palavra: destaque aproximado, proporcional ao texto.
            tokens = cue['text'].split()
            weight = sum(len(t) for t in tokens)
            cursor = cue['start']
            matched = []
            for token in tokens:
                end = cursor + (cue['end'] - cue['start']) * len(token) / weight
                matched.append(dict(start=cursor, end=end, text=token))
                cursor = end
        # Frases longas viram blocos sucessivos, mantendo no máximo duas linhas.
        groups, group = [], []
        for word in matched:
            candidate = group + [word]
            text = ' '.join(clean(w['text']) for w in candidate)
            if group and (len(candidate) > 6 or len(textwrap.wrap(text, line_limit)) > 2):
                groups.append(group)
                group = []
            group.append(word)
        if group:
            groups.append(group)
        for group in groups:
            tokens = [clean(w['text']) for w in group]
            line_width = max(line_limit, math.ceil(len(' '.join(tokens)) / 2) + 1)
            # Quebra entre palavras; tokens excepcionalmente longos continuam legíveis.
            split = None
            if len(' '.join(tokens)) > line_width:
                split = min(range(1, len(tokens)), key=lambda n: abs(len(' '.join(tokens[:n])) - len(' '.join(tokens[n:])))) if len(tokens) > 1 else None
            def render(active=None):
                parts = []
                for index, token in enumerate(tokens):
                    color = r'{\c&H18C5F5&}' if index == active else r'{\c&HFFFFFF&}'
                    parts.append((color if style == 'destaque' else '') + token)
                    if split == index + 1:
                        parts.append(r'\N')
                return ' '.join(parts).replace(r' \N ', r'\N')
            start, end = max(cue['start'], group[0]['start']), min(cue['end'], group[-1]['end'])
            if style != 'destaque':
                events.append((start, end, render()))
            else:
                if group[0]['start'] > cue['start'] and group is groups[0]:
                    events.append((cue['start'], start, render()))
                for index, word in enumerate(group):
                    word_end = min(end, group[index + 1]['start']) if index + 1 < len(group) else end
                    events.append((max(start, word['start']), word_end, render(index)))
    body = ''.join(f'Dialogue: 0,{ass_time(start)},{ass_time(end)},Default,,0,0,0,,{text}\n' for start, end, text in events if round(end * 100) > round(start * 100))
    if not body:
        raise ValueError('Legendas curtas demais para serem exibidas.')
    Path(target).write_text(header + body, encoding='utf-8')
    return target
