#!/usr/bin/env python3
"""Download e edição do GTASix7, sem dependências Python externas."""
import argparse
import contextlib
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent


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


def edit(source, creator, caption='', hook='', cut=''):
    require('ffmpeg', 'ffprobe', 'fc-match')
    creator_name(creator)
    source = Path(source).expanduser().resolve()
    if not source.is_file():
        raise ValueError(f'Vídeo não encontrado: {source}')
    metadata = json.loads(run(['ffprobe', '-v', 'error', '-show_streams', '-show_format', '-of', 'json', source], capture_output=True, text=True).stdout)
    videos = [s for s in metadata['streams'] if s['codec_type'] == 'video' and not s.get('disposition', {}).get('attached_pic')]
    if not videos:
        raise ValueError('O arquivo não tem uma faixa de vídeo.')
    duration = float(videos[0].get('duration') or metadata['format'].get('duration', 0))
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError('Não foi possível determinar a duração do vídeo.')
    start, length = cut_bounds(cut, duration)
    audio = next((s for s in metadata['streams'] if s['codec_type'] == 'audio'), None)
    font = run(['fc-match', '-f', '%{file}', 'Montserrat:style=ExtraBold'], capture_output=True, text=True).stdout
    if not Path(font).is_file():
        raise ValueError('Fonte não encontrada. Execute ./instalar.sh.')
    encoders = run(['ffmpeg', '-hide_banner', '-encoders'], capture_output=True, text=True).stdout
    if 'libx264' in encoders:
        encoding = ['-c:v', 'libx264', '-preset', 'fast', '-crf', '20']
    elif 'libopenh264' in encoders:
        encoding = ['-c:v', 'libopenh264', '-b:v', '8M']
    else:
        raise ValueError('FFmpeg sem encoder H.264: instale libx264 ou libopenh264.')
    output_dir = ROOT / 'prontos'
    output_dir.mkdir(exist_ok=True)
    # Criador e variante evitam sobrescrever cortes diferentes do mesmo vídeo.
    variant = hashlib.sha256(json.dumps([creator, caption, hook, cut], ensure_ascii=False).encode()).hexdigest()[:10]
    stem = re.sub(r'[^\w.-]', '_', source.stem)[:100]
    output = output_dir / f'{stem}_{variant}_gtasix7.mp4'
    with lock(output_dir / '.edicao.lock'), tempfile.TemporaryDirectory(prefix='gtasix7-') as tmp:
        temp = Path(tmp)
        (temp / 'font.otf').symlink_to(font)
        (temp / 'creator.txt').write_text(f'via {creator}', encoding='utf-8')
        (temp / 'hook.txt').write_text(hook.replace(' / ', '\n'), encoding='utf-8')
        draw = f'drawtext=fontfile={temp}/font.otf:expansion=none'
        graph = (
            f'[0:{videos[0]["index"]}]setpts=PTS-STARTPTS,fps=30,split=2[bg0][fg0];'
            '[bg0]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1,boxblur=20:2[bg];'
            '[fg0]scale=1080:1920:force_original_aspect_ratio=decrease:force_divisible_by=2,setsar=1[fg];'
            '[bg][fg]overlay=(W-w)/2:(H-h)/2,'
            f"{draw}:text='GTASix7':fontsize=64:fontcolor=white:borderw=4:bordercolor=black@0.8:x=(w-text_w)/2:y=140,"
            f'{draw}:textfile={temp}/creator.txt:fontsize=36:fontcolor=white:borderw=3:bordercolor=black@0.8:x=(w-text_w)/2:y=h-220'
        )
        if hook:
            graph += f",{draw}:textfile={temp}/hook.txt:fontsize=68:fontcolor=black:line_spacing=12:box=1:boxcolor=0xF5C518:boxborderw=24:x=(w-text_w)/2:y=330:enable='lt(t,3)'"
        graph += f',trim=duration={length},setpts=PTS-STARTPTS,format=yuv420p[body];'
        audio_source = f'[0:{audio["index"]}]' if audio else 'anullsrc=r=48000:cl=stereo,'
        graph += f'{audio_source}aresample=48000,aformat=channel_layouts=stereo,asetpts=PTS-STARTPTS,apad,atrim=duration={length}[sound];'
        graph += (
            'color=c=0x111111:s=1080x1920:d=2:r=30,'
            f"{draw}:text='GTASix7':fontsize=120:fontcolor=white:x=(w-text_w)/2:y=(h/2)-140,"
            f"{draw}:text='siga pra mais GTA 6':fontsize=52:fontcolor=0xF5C518:x=(w-text_w)/2:y=(h/2)+40,format=yuv420p[outro];"
            'anullsrc=r=48000:cl=stereo,atrim=duration=2[end_sound];'
            '[body][sound][outro][end_sound]concat=n=2:v=1:a=1[v][a]'
        )
        run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-threads', '2', '-filter_complex_threads', '2',
             '-ss', str(start), '-t', str(length), '-i', source, '-filter_complex', graph,
             '-map', '[v]', '-map', '[a]', *encoding, '-threads', '2', '-pix_fmt', 'yuv420p',
             '-r', '30', '-c:a', 'aac', '-b:a', '160k', '-ar', '48000', '-ac', '2', '-movflags', '+faststart', temp / 'final.mp4'])
        # Só troca o resultado final depois de uma renderização completa.
        staging = output.with_suffix('.mp4.tmp')
        try:
            shutil.copyfile(temp / 'final.mp4', staging)
            staging.replace(output)
        finally:
            staging.unlink(missing_ok=True)
        output.with_suffix('.txt').write_text(f'{caption}\n\n🎥 Créditos: {creator} (repostado com autorização)\n#gta6 #gtavi #gta #gta6trailer #gtasix7\n', encoding='utf-8')
    print(f'Pronto: {output}\nLegenda: {output.with_suffix(".txt")}', flush=True)
    return output


def download(args):
    require('yt-dlp')
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
                if url in done:
                    print(f'Já feito: {url}', flush=True)
                    continue
                key = hashlib.sha256(url.encode()).hexdigest()[:16]
                log = ROOT / 'logs' / f'{name}_{key}.log'
                template = ROOT / 'recebidos' / f'{name}_{key}.%(ext)s'
                command = ['yt-dlp', '--no-playlist', '--restrict-filenames', '--retries', '3', '--socket-timeout', '30',
                           '-f', 'bv*+ba/b', '--merge-output-format', 'mp4', '--remux-video', 'mp4',
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
                    edit(paths[-1], creator, caption, hook, cut)
                with history.open('a') as handle:
                    handle.write(url + '\n')
                done.add(url)
            except (ValueError, OSError, subprocess.CalledProcessError, json.JSONDecodeError) as error:
                failed += 1
                print(f'Falha na linha {number}: {error}', file=sys.stderr, flush=True)
                if log:
                    print(f'Detalhes do download: {log}', file=sys.stderr)
    return 1 if failed else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest='action', required=True)
    editor = subs.add_parser('editar', help='Editar arquivo local')
    editor.add_argument('source')
    editor.add_argument('creator')
    editor.add_argument('caption', nargs='?', default='')
    editor.add_argument('hook', nargs='?', default='')
    editor.add_argument('cut', nargs='?', default='')
    downloader = subs.add_parser('baixar', help='Baixar link ou processar fila')
    downloader.add_argument('url', nargs='?')
    downloader.add_argument('--criador', dest='creator')
    downloader.add_argument('--legenda', dest='caption', default='')
    downloader.add_argument('--gancho', dest='hook', default='')
    downloader.add_argument('--corte', dest='cut', default='')
    downloader.add_argument('--fila', dest='queue', default=str(ROOT / 'fila.txt'))
    downloader.add_argument('--cookies-do-navegador', dest='cookies_browser', metavar='NAVEGADOR')
    args = parser.parse_args()
    try:
        if args.action == 'editar':
            edit(args.source, args.creator, args.caption, args.hook, args.cut)
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
