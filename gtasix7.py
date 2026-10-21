#!/usr/bin/env python3
"""Download até 4K e edição vertical com áudio e legendas locais."""
import argparse
import contextlib
import fcntl
import gc
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import wave
from dataclasses import asdict, dataclass, replace
from fractions import Fraction
from urllib.parse import urlsplit
from legendas import create_ass

ROOT = Path(__file__).resolve().parent

PROFILES = {
    'padrao': dict(framing='ajustar', focus='centro', subtitle_style='discreta', hook_duration=3, brand='padrao', outro=2, fps='auto', audio_mode='normalizar'),
    'gameplay': dict(framing='ajustar', focus='centro', subtitle_style='discreta', hook_duration=3, brand='discreta', outro=0, fps='auto', audio_mode='original'),
    'comentario': dict(framing='preencher', focus='centro', subtitle_style='destaque', hook_duration=2, brand='discreta', outro=0, fps='auto', audio_mode='limpar'),
    'noticia': dict(framing='ajustar', focus='centro', subtitle_style='discreta', hook_duration=2, brand='discreta', outro=1, fps='auto', audio_mode='normalizar'),
}


@dataclass(frozen=True)
class EditOptions:
    resolution: str = 'auto'
    max_duration: float = 60
    audio_mode: str | None = None
    subtitles: str = 'auto'
    subtitle_file: str | None = None
    model: str = 'base'
    language: str = 'auto'
    profile: str = 'padrao'
    framing: str | None = None
    focus: str | None = None
    subtitle_style: str | None = None
    hook_duration: float | None = None
    brand: str | None = None
    outro: float | None = None
    fps: str | None = None
    preview: bool = False
    cover_time: float | None = None

    def validate(self):
        self = resolve_options(self)
        if self.resolution not in {'auto', '1080', '2160'}:
            raise ValueError('Resolução inválida: use auto, 1080 ou 2160.')
        if not math.isfinite(self.max_duration) or not 3 <= self.max_duration <= 60:
            raise ValueError('Duração máxima deve ficar entre 3 e 60 segundos (inclui cartão final).')
        if self.audio_mode not in {'original', 'normalizar', 'limpar'}:
            raise ValueError('Áudio inválido: use original, normalizar ou limpar.')
        if self.subtitles not in {'auto', 'nenhuma'}:
            raise ValueError('Legendas inválidas: use auto ou nenhuma.')
        if self.subtitle_file and self.subtitles == 'nenhuma':
            raise ValueError('Não combine --srt com --legendas nenhuma.')
        if self.subtitle_file and not Path(self.subtitle_file).expanduser().is_file():
            raise ValueError(f'Arquivo SRT não encontrado: {self.subtitle_file}')
        if self.language != 'auto' and not re.fullmatch(r'[a-z]{2,3}', self.language):
            raise ValueError('Idioma inválido: use auto, pt, en ou outro código de idioma.')
        for field, allowed in [('framing', {'ajustar', 'preencher'}), ('focus', {'centro', 'esquerda', 'direita'}),
                               ('subtitle_style', {'discreta', 'destaque'}), ('brand', {'discreta', 'padrao'}), ('fps', {'auto', '30', '60'})]:
            if getattr(self, field) not in allowed:
                raise ValueError(f'Opção inválida: {field}.')
        if not math.isfinite(self.outro) or not 0 <= self.outro <= 5 or self.outro >= self.max_duration:
            raise ValueError('Cartão final deve ter de 0 a 5 segundos e caber na duração máxima.')
        if not math.isfinite(self.hook_duration) or not 0 <= self.hook_duration <= 10:
            raise ValueError('Duração do gancho deve ficar entre 0 e 10 segundos.')
        if self.cover_time is not None and (not math.isfinite(self.cover_time) or self.cover_time < 0):
            raise ValueError('Tempo da capa deve ser um número positivo ou zero.')


def resolve_options(options):
    if options.profile not in PROFILES:
        raise ValueError('Perfil inválido: use padrao, gameplay, comentario ou noticia.')
    return replace(options, **{key: value for key, value in PROFILES[options.profile].items() if getattr(options, key) is None})


def output_fps(video, requested, preview=False):
    try:
        rate = Fraction(video.get('avg_frame_rate') or video.get('r_frame_rate') or '30') if requested == 'auto' else Fraction(requested)
        if rate <= 0:
            rate = Fraction(30)
    except (ValueError, ZeroDivisionError):
        rate = Fraction(30)
    return min(rate, Fraction(30 if preview else 60))


def output_size(video, resolution):
    width = int(resolution) if resolution != 'auto' else (2160 if max(video['width'], video['height']) >= 3840 else 1080)
    return width, width * 16 // 9


def body_duration(length, limit, outro=2, fps=30):
    return max(1, math.floor(min(length, limit - outro) * fps)) / fps


def srt_time(seconds):
    milliseconds = max(0, round(seconds * 1000))
    hours, remainder = divmod(milliseconds, 3600000)
    minutes, remainder = divmod(remainder, 60000)
    seconds, milliseconds = divmod(remainder, 1000)
    return f'{hours:02}:{minutes:02}:{seconds:02},{milliseconds:03}'


def write_subtitles(segments, target, duration, word_target=None):
    """Grupos curtos de palavras; os tempos são relativos ao trecho extraído."""
    cues, timings = [], []
    for segment in segments:
        if getattr(segment, 'no_speech_prob', 0) > 0.6:
            continue
        words = list(getattr(segment, 'words', None) or [])
        timings.extend(dict(start=max(0, w.start), end=min(duration, w.end), text=w.word.strip()) for w in words if w.end > 0 and w.start < duration)
        if not words:
            groups = [(segment.start, segment.end, segment.text)]
        else:
            groups, group = [], []
            for word in words:
                if group and (len(group) >= 6 or word.end - group[0].start > 3):
                    groups.append((group[0].start, group[-1].end, ''.join(w.word for w in group)))
                    group = []
                group.append(word)
            if group:
                groups.append((group[0].start, group[-1].end, ''.join(w.word for w in group)))
        for start, end, text in groups:
            start, end = max(0, start), min(end, duration)
            text = re.sub(r'[{}<>\\]', '', text)
            text = ' '.join(text.split())
            if text and end > start:
                wrapped = '\n'.join(textwrap.wrap(text, width=32))
                cues.append(f'{len(cues) + 1}\n{srt_time(start)} --> {srt_time(end)}\n{wrapped}\n')
    if cues:
        target.write_text('\n'.join(cues), encoding='utf-8')
        if word_target:
            word_target.write_text(json.dumps(timings, ensure_ascii=False), encoding='utf-8')
    return bool(cues)


def transcribe(source, audio_index, start, length, temp, options):
    try:
        from faster_whisper import WhisperModel
        import numpy as np
    except ImportError:
        raise ValueError('Legendas automáticas precisam do faster-whisper. Execute ./instalar-legendas.sh ou use --legendas nenhuma.') from None
    wav = temp / 'speech.wav'
    run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-ss', start, '-t', length,
         '-i', source, '-map', f'0:{audio_index}', '-vn', '-ac', '1', '-ar', '16000', '-c:a', 'pcm_s16le', wav])
    # PCM extraído pelo FFmpeg evita diferenças entre versões do decodificador PyAV.
    with wave.open(str(wav), 'rb') as handle:
        samples = np.frombuffer(handle.readframes(handle.getnframes()), dtype='<i2').astype(np.float32) / 32768.0
    print(f'Transcrevendo localmente (Whisper {options.model}, CPU int8)...', flush=True)
    model = None
    try:
        model = WhisperModel(options.model, device='cpu', compute_type='int8', cpu_threads=2, num_workers=1)
        segments, _ = model.transcribe(samples, language=None if options.language == 'auto' else options.language,
                                       beam_size=3, word_timestamps=True, vad_filter=True, condition_on_previous_text=False)
        target = temp / 'subtitles.srt'
        result = target if write_subtitles(segments, target, length, temp / 'words.json') else None
    except Exception as error:
        raise ValueError(f'Falha na transcrição: {error}. Confira modelo/idioma; a primeira execução precisa de internet para baixar o modelo.') from error
    finally:
        del model
        gc.collect()
    if result is None:
        print('Nenhuma fala detectada; vídeo segue sem legendas.', flush=True)
    return result


def run(args, **kwargs):
    return subprocess.run([str(arg) for arg in args], check=True, **kwargs)


def require(*commands):
    for command in commands:
        if not shutil.which(command):
            raise ValueError(f'Dependência ausente: {command}. Execute ./instalar.sh.')


def creator_name(value):
    if not re.fullmatch(r'@?[A-Za-z0-9_.-]{1,80}', value) or value.lstrip('@') in {'.', '..'}:
        raise ValueError('Criador inválido: use @perfil, sem espaços ou barras.')
    return value.lstrip('@')


def validate_url(value):
    parsed = urlsplit(value)
    if parsed.scheme not in {'https', 'http'} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('Informe um link HTTP/HTTPS válido, sem credenciais.')


def cut_bounds(value, duration):
    start, end = 0.0, duration
    if value:
        match = re.fullmatch(r'(\d+(?:\.\d+)?)-(\d+(?:\.\d+)?)', value)
        if not match:
            raise ValueError('Corte inválido: use início-fim em segundos, por exemplo 3-25.')
        start, end = map(float, match.groups())
        if not (0 <= start < end <= duration + 0.05):
            raise ValueError(f'Corte fora do vídeo ({duration:.2f}s) ou fim anterior ao início.')
    return start, min(end, duration) - start


@contextlib.contextmanager
def lock(path):
    with path.open('a') as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('Já existe um processamento em andamento.') from None
        yield


def edit(source, creator, caption='', hook='', cut='', *, options=None):
    options = resolve_options(options or EditOptions())
    options.validate()
    require('ffmpeg', 'ffprobe', 'fc-match')
    creator_name(creator)
    source = Path(source).expanduser().resolve()
    if not source.is_file():
        raise ValueError(f'Vídeo não encontrado: {source}')
    metadata = json.loads(run(['ffprobe', '-v', 'error', '-show_streams', '-show_format', '-of', 'json', source], capture_output=True, text=True).stdout)
    videos = [s for s in metadata['streams'] if s['codec_type'] == 'video' and not s.get('disposition', {}).get('attached_pic')]
    if not videos:
        raise ValueError('O arquivo não tem uma faixa de vídeo.')
    video = videos[0]
    duration = float(video.get('duration') or metadata['format'].get('duration', 0))
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError('Não foi possível determinar a duração do vídeo.')
    start, length = cut_bounds(cut, duration)
    rate = output_fps(video, options.fps, options.preview)
    fps, frame_rate = float(rate), str(rate)
    outro = round(options.outro * fps) / fps
    length = body_duration(length, options.max_duration, outro, fps)
    if options.cover_time is not None and options.cover_time >= length:
        raise ValueError(f'Tempo da capa deve estar dentro do corpo editado ({length:.2f}s), sem o cartão final.')
    width, height = (360, 640) if options.preview else output_size(video, options.resolution)
    factor = width / 1080
    audio = next((s for s in metadata['streams'] if s['codec_type'] == 'audio'), None)
    font = run(['fc-match', '-f', '%{file}', 'Montserrat:style=ExtraBold'], capture_output=True, text=True).stdout
    if not Path(font).is_file():
        raise ValueError('Fonte não encontrada. Execute ./instalar.sh.')
    encoders = run(['ffmpeg', '-hide_banner', '-encoders'], capture_output=True, text=True).stdout
    if 'libx264' in encoders:
        encoding = ['-c:v', 'libx264', '-preset', 'fast', '-crf', '25' if options.preview else '18']
    elif 'libopenh264' in encoders:
        bitrate = '1M' if options.preview else ('48M' if width == 2160 and fps > 30 else '32M' if width == 2160 else '12M' if fps > 30 else '8M')
        encoding = ['-c:v', 'libopenh264', '-b:v', bitrate]
    else:
        raise ValueError('FFmpeg sem encoder H.264: instale libx264 ou libopenh264.')
    output_dir = ROOT / 'prontos'
    if options.preview:
        output_dir /= 'previas'
    output_dir.mkdir(exist_ok=True, parents=True)
    subtitle_hash = hashlib.sha256(Path(options.subtitle_file).expanduser().read_bytes()).hexdigest() if options.subtitle_file else None
    variant = hashlib.sha256(json.dumps([creator, caption, hook, cut, asdict(options), subtitle_hash], ensure_ascii=False).encode()).hexdigest()[:10]
    stem = re.sub(r'[^\w.-]', '_', source.stem)[:100]
    output = output_dir / f'{stem}_{variant}_{"previa" if options.preview else "gtasix7"}.mp4'
    print(f'Renderizando: {width}x{height}, {frame_rate} fps, {length + outro:.2f}s, perfil {options.profile}.', flush=True)
    with lock(ROOT / 'prontos' / '.edicao.lock'), tempfile.TemporaryDirectory(prefix='gtasix7-') as tmp:
        temp = Path(tmp)
        (temp / 'font.otf').symlink_to(font)
        (temp / 'creator.txt').write_text(f'via {creator}', encoding='utf-8')
        (temp / 'hook.txt').write_text(hook.replace(' / ', '\n'), encoding='utf-8')
        subtitles = None
        if options.subtitle_file:
            subtitles = temp / 'subtitles.srt'
            shutil.copyfile(Path(options.subtitle_file).expanduser(), subtitles)
        elif options.subtitles == 'auto' and audio:
            subtitles = transcribe(source, audio['index'], start, length, temp, options)
        ass = create_ass(subtitles, temp / 'subtitles.ass', width, height, length, options.subtitle_style, temp / 'words.json') if subtitles else None
        draw = f'drawtext=fontfile={temp}/font.otf:expansion=none'
        graph = f'[0:{video["index"]}]setpts=PTS-STARTPTS,fps={frame_rate},'
        if options.framing == 'ajustar':
            graph += (
                'split=2[bg0][fg0];'
                f'[bg0]scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},setsar=1,boxblur=20:2[bg];'
                f'[fg0]scale={width}:{height}:force_original_aspect_ratio=decrease:force_divisible_by=2,setsar=1[fg];'
                '[bg][fg]overlay=(W-w)/2:(H-h)/2,'
            )
        else:
            focus = {'centro': '(iw-ow)/2', 'esquerda': '0', 'direita': 'iw-ow'}[options.focus]
            graph += f'scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height}:x={focus}:y=(ih-oh)/2,setsar=1,'
        brand_size, opacity = (40, '0.65') if options.brand == 'discreta' else (64, '1')
        graph += (
            f"{draw}:text='GTASix7':fontsize={brand_size*factor}:fontcolor=white@{opacity}:borderw={3*factor}:bordercolor=black@0.6:x=(w-text_w)/2:y={140*factor},"
            f'{draw}:textfile={temp}/creator.txt:fontsize={36*factor}:fontcolor=white:borderw={3*factor}:bordercolor=black@0.8:x=(w-text_w)/2:y=h-{220*factor}'
        )
        if hook and options.hook_duration > 0:
            graph += f",{draw}:textfile={temp}/hook.txt:fontsize={68*factor}:fontcolor=black:line_spacing={12*factor}:box=1:boxcolor=0xF5C518:boxborderw={24*factor}:x=(w-text_w)/2:y={330*factor}:enable='lt(t,{options.hook_duration})'"
        if ass:
            graph += f',ass=filename={ass}:fontsdir={temp}'
        graph += f',trim=duration={length},setpts=PTS-STARTPTS,format=yuv420p[body];'
        audio_source = f'[0:{audio["index"]}]' if audio else 'anullsrc=r=48000:cl=stereo,'
        graph += f'{audio_source}aresample=48000,aformat=channel_layouts=stereo,asetpts=PTS-STARTPTS,atrim=duration={length},'
        if audio and options.audio_mode == 'limpar':
            graph += 'afftdn=nf=-25,'
        if audio and options.audio_mode != 'original':
            graph += 'loudnorm=I=-16:TP=-1.5:LRA=11,'
        graph += f'aresample=48000,apad,atrim=duration={length}[sound];'
        if outro:
            graph += (
                f'color=c=0x111111:s={width}x{height}:d={outro}:r={frame_rate},'
                f"{draw}:text='GTASix7':fontsize={120*factor}:fontcolor=white:x=(w-text_w)/2:y=(h/2)-{140*factor},"
                f"{draw}:text='siga pra mais GTA 6':fontsize={52*factor}:fontcolor=0xF5C518:x=(w-text_w)/2:y=(h/2)+{40*factor},format=yuv420p[outro];"
                f'anullsrc=r=48000:cl=stereo,atrim=duration={outro}[end_sound];'
                '[body][sound][outro][end_sound]concat=n=2:v=1:a=1[v][a]'
            )
        else:
            graph += '[body]null[v];[sound]anull[a]'
        run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-threads', '2', '-filter_complex_threads', '2',
             '-ss', str(start), '-t', str(length), '-i', source, '-filter_complex', graph,
             '-map', '[v]', '-map', '[a]', *encoding, '-threads', '2', '-pix_fmt', 'yuv420p',
             '-r', frame_rate, '-c:a', 'aac', '-b:a', '192k', '-ar', '48000', '-ac', '2', '-t', str(options.max_duration), '-movflags', '+faststart', temp / 'final.mp4'])
        if options.cover_time is not None:
            cover_index = math.floor(options.cover_time * fps)
            run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-i', temp / 'final.mp4',
                 '-vf', f'select=eq(n\\,{cover_index})', '-frames:v', '1', '-q:v', '2', temp / 'cover.jpg'])
        staging = output.with_suffix('.mp4.tmp')
        try:
            shutil.copyfile(temp / 'final.mp4', staging)
            staging.replace(output)
        finally:
            staging.unlink(missing_ok=True)
        output.with_suffix('.txt').write_text(f'{caption}\n\n🎥 Créditos: {creator} (repostado com autorização)\n#gta6 #gtavi #gta #gta6trailer #gtasix7\n', encoding='utf-8')
        for suffix, artifact in [('.srt', subtitles), ('.ass', ass), ('.jpg', temp / 'cover.jpg' if options.cover_time is not None else None)]:
            if artifact:
                shutil.copyfile(artifact, output.with_suffix(suffix))
            else:
                output.with_suffix(suffix).unlink(missing_ok=True)
        output.with_suffix('.json').write_text(json.dumps(dict(
            schema_version=1, source=str(source), creator=creator, caption=caption, hook=hook, cut=cut,
            options=asdict(options), rendered=dict(start=start, body_duration=length, outro_duration=outro, width=width, height=height, fps=frame_rate),
            video=str(output), cover=str(output.with_suffix('.jpg')) if options.cover_time is not None else None,
            subtitle_timing='word' if (temp / 'words.json').exists() else 'estimated' if subtitles else None,
        ), ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'Pronto: {output}\nLegenda do post: {output.with_suffix(".txt")}', flush=True)
    if options.preview:
        print('Prévia: a URL não foi marcada como concluída. Retire --previa para exportar a versão final.', flush=True)
    return output

def download(args):
    require('yt-dlp')
    options = options_from_args(args)
    options.validate()
    # Diretórios e registros locais nunca entram no repositório.
    for name in ('recebidos', 'prontos', 'logs'):
        (ROOT / name).mkdir(exist_ok=True)
    history = ROOT / 'processados.txt'
    failed = 0
    with lock(ROOT / '.download.lock'):
        done = set(history.read_text().splitlines()) if history.exists() else set()
        if args.url:
            if not args.creator:
                raise ValueError('Informe --criador @perfil junto com o link.')
            rows = [(1, [args.creator, args.url, args.caption, args.hook, args.cut])]
        else:
            queue = Path(args.queue)
            if not queue.is_file():
                raise ValueError(f'Fila não encontrada: {queue}')
            rows = [(n, line.split('|')) for n, line in enumerate(queue.read_text(encoding='utf-8').splitlines(), 1) if line.strip() and not line.lstrip().startswith('#')]
        if not rows:
            print('Fila vazia. Adicione um link ou preencha fila.txt.')
        for number, fields in rows:
            log = None
            try:
                if not 2 <= len(fields) <= 5:
                    raise ValueError('Use criador | URL | legenda | gancho | corte (sem | nos textos).')
                creator, url, caption, hook, cut = ([s.strip() for s in fields] + [''] * 5)[:5]
                name = creator_name(creator)
                validate_url(url)
                if cut:
                    cut_bounds(cut, float('inf'))
                if url in done and not getattr(args, 'redo', False) and not options.preview:
                    print(f'Já feito: {url}', flush=True)
                    continue
                key = hashlib.sha256(url.encode()).hexdigest()[:16]
                log = ROOT / 'logs' / f'{name}_{key}.log'
                template = ROOT / 'recebidos' / f'{name}_{key}.%(ext)s'
                command = ['yt-dlp', '--no-playlist', '--restrict-filenames', '--retries', '3', '--socket-timeout', '30',
                           '-f', 'bv*[height<=?3840][width<=?3840]+ba/b[height<=?3840][width<=?3840]',
                           '--merge-output-format', 'mkv',
                           '--print', 'after_move:filepath', '-o', str(template)]
                if args.cookies_browser:
                    command += ['--cookies-from-browser', args.cookies_browser]
                print(f'Baixando: {url}', flush=True)
                with log.open('w') as errors:
                    result = run([*command, '--', url], stdout=subprocess.PIPE, stderr=errors, text=True)
                    paths = result.stdout.strip().splitlines()
                    if not paths or not Path(paths[-1]).is_file():
                        raise ValueError(f'O download não retornou um arquivo. Veja {log}')
                    # FFmpeg mantém erros no terminal; yt-dlp registra detalhes em logs/.
                    edit(paths[-1], creator, caption, hook, cut, options=options)
                if not options.preview:
                    with history.open('a') as handle:
                        handle.write(url + '\n')
                    done.add(url)
            except (ValueError, OSError, subprocess.CalledProcessError, json.JSONDecodeError) as error:
                failed += 1
                print(f'Falha na linha {number}: {error}', file=sys.stderr, flush=True)
                if log:
                    print(f'Detalhes do download: {log}', file=sys.stderr)
    return 1 if failed else 0


def options_from_args(args):
    defaults = EditOptions()
    return resolve_options(EditOptions(**{name: getattr(args, name, value) for name, value in asdict(defaults).items()}))


def add_edit_options(parser):
    parser.add_argument('--perfil', dest='profile', choices=list(PROFILES), default='padrao', help='conjunto de ajustes; opções explícitas têm prioridade')
    parser.add_argument('--enquadramento', dest='framing', choices=['ajustar', 'preencher'], help='ajustar: imagem inteira e fundo desfocado; preencher: recorte vertical')
    parser.add_argument('--foco', dest='focus', choices=['centro', 'esquerda', 'direita'], help='posição horizontal do recorte em preencher')
    parser.add_argument('--estilo-legenda', dest='subtitle_style', choices=['discreta', 'destaque'], help='destaque usa tempos por palavra do Whisper; SRT usa estimativa')
    parser.add_argument('--gancho-duracao', dest='hook_duration', type=float, help='0 a 10 segundos; 0 desativa o gancho')
    parser.add_argument('--marca', dest='brand', choices=['discreta', 'padrao'])
    parser.add_argument('--outro', type=float, help='0 a 5 segundos; 0 remove o cartão final')
    parser.add_argument('--fps', choices=['auto', '30', '60'], help='auto preserva a taxa média da fonte até 60 fps')
    parser.add_argument('--previa', dest='preview', action='store_true', help='360x640, até 30 fps; não altera o histórico de concluídos')
    parser.add_argument('--capa-tempo', dest='cover_time', type=float, help='exporta JPG; segundos relativos ao início do trecho editado')
    parser.add_argument('--resolucao', dest='resolution', choices=['auto', '1080', '2160'], default='auto', help='auto: 4K vertical se a fonte tiver 4K; senão 1080x1920')
    parser.add_argument('--duracao-max', dest='max_duration', type=float, default=60, help='3 a 60 segundos, incluindo cartão final (padrão: 60)')
    parser.add_argument('--audio', dest='audio_mode', choices=['original', 'normalizar', 'limpar'], default=None, help='limpar: redução leve de ruído + normalização')
    parser.add_argument('--legendas', dest='subtitles', choices=['auto', 'nenhuma'], default='auto', help='transcrição local incorporada ao vídeo (padrão: auto)')
    parser.add_argument('--srt', dest='subtitle_file', help='usar SRT existente, com tempos relativos ao início do corte')
    parser.add_argument('--modelo-whisper', dest='model', choices=['tiny', 'base', 'small'], default='base')
    parser.add_argument('--idioma', dest='language', default='auto', help='idioma da fala: auto, pt, en...; não traduz')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest='action', required=True)
    editor = subs.add_parser('editar', help='Editar arquivo local')
    editor.add_argument('source')
    editor.add_argument('creator')
    editor.add_argument('caption', nargs='?', default='')
    editor.add_argument('hook', nargs='?', default='')
    editor.add_argument('cut', nargs='?', default='')
    add_edit_options(editor)
    downloader = subs.add_parser('baixar', help='Baixar link ou processar fila')
    downloader.add_argument('url', nargs='?')
    downloader.add_argument('--criador', dest='creator')
    downloader.add_argument('--legenda', dest='caption', default='')
    downloader.add_argument('--gancho', dest='hook', default='')
    downloader.add_argument('--corte', dest='cut', default='')
    downloader.add_argument('--fila', dest='queue', default=str(ROOT / 'fila.txt'))
    downloader.add_argument('--cookies-do-navegador', dest='cookies_browser', metavar='NAVEGADOR')
    downloader.add_argument('--refazer', dest='redo', action='store_true', help='reprocessar URLs já concluídas, usando as opções atuais')
    add_edit_options(downloader)
    args = parser.parse_args()
    try:
        if args.action == 'editar':
            edit(args.source, args.creator, args.caption, args.hook, args.cut, options=options_from_args(args))
            return 0
        return download(args)
    except (ValueError, OSError, subprocess.CalledProcessError, json.JSONDecodeError) as error:
        print(f'Erro: {error}', file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print('\nInterrompido. Vídeo incompleto não foi marcado como processado.', file=sys.stderr)
        return 130


if __name__ == '__main__':
    sys.exit(main())
