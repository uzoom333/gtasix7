"""Regressões e integração local real com FFmpeg, ffprobe e yt-dlp."""
import functools
import http.server
import json
import os
import shutil
from types import SimpleNamespace
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch

import gtasix7 as app


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='gtasix7-tests-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.old_root = app.ROOT
        self.options = app.EditOptions(subtitles='nenhuma')
        app.ROOT = self.root
        self.addCleanup(setattr, app, 'ROOT', self.old_root)

    def sample(self, audio=False):
        path = self.root / ("amostra com 'aspas'.mp4" if audio else 'silencioso.mp4')
        command = ['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'testsrc2=s=320x180:r=24:d=2']
        if audio:
            command += ['-f', 'lavfi', '-i', 'sine=frequency=440:duration=2']
        app.run([*command, '-c:v', 'mpeg4', '-q:v', '5', '-c:a', 'aac', path])
        return path

    def assert_video(self, path, expected_duration):
        data = json.loads(app.run(['ffprobe', '-v', 'error', '-show_streams', '-show_format', '-of', 'json', path], capture_output=True, text=True).stdout)
        video = next(s for s in data['streams'] if s['codec_type'] == 'video')
        audio = next(s for s in data['streams'] if s['codec_type'] == 'audio')
        self.assertEqual((video['width'], video['height'], video['pix_fmt']), (1080, 1920, 'yuv420p'))
        self.assertEqual(video['r_frame_rate'], '30/1')
        self.assertEqual(audio['channels'], 2)
        self.assertEqual(audio['sample_rate'], '48000')
        self.assertAlmostEqual(float(data['format']['duration']), expected_duration, delta=0.15)
        self.assertAlmostEqual(float(video['duration']), float(audio['duration']), delta=0.15)
        # Decodifica o arquivo inteiro, incluindo a transição para o cartão final.
        app.run(['ffmpeg', '-v', 'error', '-xerror', '-i', path, '-f', 'null', '-'])

    def test_audio_cut_special_text_and_invalid_cut(self):
        source = self.sample(audio=True)
        output = app.edit(source, '@parceiro', 'Legenda: "teste" 100%', "olha: 'isso' 100% / %{n}", '0.5-1.5', options=self.options)
        self.assert_video(output, 3)
        self.assertIn('Créditos: @parceiro', output.with_suffix('.txt').read_text())
        with self.assertRaises(ValueError):
            app.edit(source, '@parceiro', cut='1-7', options=self.options)
        self.assertTrue(output.exists())

    def test_silent_video(self):
        output = app.edit(self.sample(), '@parceiro', options=self.options)
        self.assert_video(output, 4)

    def test_resolution_and_limits(self):
        self.assertEqual(app.output_size({'width': 3840, 'height': 2160}, 'auto'), (2160, 3840))
        self.assertEqual(app.output_size({'width': 2160, 'height': 3840}, 'auto'), (2160, 3840))
        self.assertEqual(app.output_size({'width': 1920, 'height': 1080}, 'auto'), (1080, 1920))
        self.assertEqual(app.body_duration(90, 60), 58)
        self.assertLessEqual(app.body_duration(59.99, 60) + 2, 60)
        for limit in [0, 2, 61, float('nan')]:
            with self.assertRaises(ValueError):
                app.EditOptions(max_duration=limit).validate()

    def test_real_4k_render(self):
        # 4K de origem, sem forçar upscale de uma amostra pequena.
        source = self.root / '4k.mp4'
        app.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'color=c=blue:s=3840x2160:r=30:d=0.2', '-c:v', 'mpeg4', source])
        output = app.edit(source, '@teste', options=self.options)
        info = json.loads(app.run(['ffprobe', '-v', 'error', '-show_streams', '-of', 'json', output], capture_output=True, text=True).stdout)
        self.assertEqual((info['streams'][0]['width'], info['streams'][0]['height']), (2160, 3840))
        app.run(['ffmpeg', '-v', 'error', '-xerror', '-i', output, '-f', 'null', '-'])

    def test_real_one_minute_limit(self):
        source = self.root / 'longo.mp4'
        app.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'color=c=blue:s=160x90:r=30:d=65', '-c:v', 'mpeg4', source])
        output = app.edit(source, '@teste', options=self.options)
        self.assert_video(output, 60)
        duration = float(app.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', output], capture_output=True, text=True).stdout)
        self.assertLessEqual(duration, 60)

    def test_external_srt_audio_cleanup_and_variant(self):
        source = self.sample(audio=True)
        srt = self.root / "legenda ' com espaços.srt"
        srt.write_text('1\n00:00:00,000 --> 00:00:01,500\nTeste de legenda incorporada\n', encoding='utf-8')
        options = app.EditOptions(subtitle_file=str(srt), audio_mode='limpar')
        output = app.edit(source, '@teste', options=options)
        self.assert_video(output, 4)
        self.assertEqual(output.with_suffix('.srt').read_text(), srt.read_text())
        old_output = output
        srt.write_text(srt.read_text().replace('Teste', 'Outro teste'))
        output = app.edit(source, '@teste', options=options)
        self.assertNotEqual(old_output, output)

    def test_word_subtitles_clamped_and_sanitized(self):
        segment = SimpleNamespace(no_speech_prob=0.1, words=[SimpleNamespace(start=0.1, end=0.8, word=' Olá'), SimpleNamespace(start=0.8, end=4, word=' {teste}<b>')])
        srt = self.root / 'test.srt'
        self.assertTrue(app.write_subtitles([segment], srt, 2))
        text = srt.read_text()
        self.assertIn('00:00:02,000', text)
        self.assertNotIn('{', text)
        self.assertNotIn('<', text)
        self.assertFalse(app.write_subtitles([SimpleNamespace(no_speech_prob=0.9)], self.root / 'silence.srt', 2))

    @unittest.skipUnless(os.environ.get('GTASIX7_TEST_ASR') == '1' and shutil.which('espeak-ng'), 'Teste Whisper opcional: GTASIX7_TEST_ASR=1 e espeak-ng')
    def test_real_portuguese_transcription_after_cut(self):
        speech = self.root / 'fala.wav'
        app.run(['espeak-ng', '-v', 'pt-br', '-s', '140', '-w', speech, 'Este é um teste de legendas automáticas. O vídeo está pronto para publicar.'])
        source = self.root / 'fala.mp4'
        app.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'color=c=0x202030:s=320x180:r=30:d=20', '-i', speech,
                 '-af', 'adelay=2000:all=1', '-c:v', 'mpeg4', '-c:a', 'aac', '-shortest', source])
        output = app.edit(source, '@teste', cut='2-8', options=app.EditOptions(language='pt', audio_mode='limpar'))
        self.assert_video(output, 8)
        self.assertTrue(output.with_suffix('.srt').is_file())
        text = output.with_suffix('.srt').read_text().lower()
        self.assertIn('teste', text)
        self.assertIn('00:00:0', text)

    def args(self):
        # Reutiliza o parser público sem depender do main.
        import argparse
        return argparse.Namespace(url=None, creator=None, caption='', hook='', cut='', queue=str(self.root / 'fila.txt'), cookies_browser=None, subtitles='nenhuma')

    def test_failures_continue_and_retry_without_recording_failure(self):
        (self.root / 'fila.txt').write_text('@x | https://example.test/falha\n@x | https://example.test/ok\n@x | https://example.test/ok\n')
        downloaded = self.root / 'download.mp4'
        downloaded.touch()
        def fake_run(command, **kwargs):
            if command[-1].endswith('/falha'):
                raise subprocess.CalledProcessError(1, command)
            return subprocess.CompletedProcess(command, 0, str(downloaded) + '\n')
        with patch.object(app, 'run', side_effect=fake_run) as fetch, patch.object(app, 'edit') as editor:
            self.assertEqual(app.download(self.args()), 1)
            self.assertEqual(fetch.call_count, 2)
            self.assertEqual(editor.call_count, 1)
        self.assertEqual((self.root / 'processados.txt').read_text(), 'https://example.test/ok\n')
        with patch.object(app, 'run', return_value=subprocess.CompletedProcess([], 0, str(downloaded) + '\n')), patch.object(app, 'edit', side_effect=ValueError('edição falhou')):
            self.assertEqual(app.download(self.args()), 1)
        self.assertEqual((self.root / 'processados.txt').read_text(), 'https://example.test/ok\n')

    def test_ytdlp_quality_caps_8k_and_keeps_vertical_4k(self):
        fixture = self.root / 'formats.json'
        fixture.write_text(json.dumps({'id': 'sample', 'title': 'sample', 'extractor': 'generic', 'webpage_url': 'https://example.test/video', 'formats': [
            {'format_id': name, 'url': f'https://example.test/{name}.mp4', 'ext': 'mp4', 'width': width, 'height': height, 'vcodec': 'h264', 'acodec': 'aac'}
            for name, width, height in [('1080', 1920, 1080), ('4k', 2160, 3840), ('8k', 7680, 4320)]
        ]}))
        (self.root / 'fila.txt').write_text('@x | https://example.test/video\n')
        downloaded = self.root / 'download.mp4'
        downloaded.touch()
        def inspect_real_selector(command, **kwargs):
            selector = command[command.index('-f') + 1]
            result = subprocess.run(['yt-dlp', '--ignore-config', '--simulate', '--no-check-formats', '--load-info-json', str(fixture),
                                     '-f', selector, '--print', 'format_id'], capture_output=True, text=True, check=True)
            self.assertEqual(result.stdout.strip(), '4k')
            return subprocess.CompletedProcess(command, 0, str(downloaded) + '\n')
        with patch.object(app, 'run', side_effect=inspect_real_selector), patch.object(app, 'edit'):
            self.assertEqual(app.download(self.args()), 0)

    def test_redo_processes_completed_url(self):
        url = 'https://example.test/video'
        (self.root / 'fila.txt').write_text(f'@x | {url}\n')
        (self.root / 'processados.txt').write_text(url + '\n')
        downloaded = self.root / 'download.mp4'
        downloaded.touch()
        args = self.args()
        args.redo = True
        with patch.object(app, 'run', return_value=subprocess.CompletedProcess([], 0, str(downloaded) + '\n')), patch.object(app, 'edit') as editor:
            self.assertEqual(app.download(args), 0)
            editor.assert_called_once()

    def test_validation_empty_queue_and_lock(self):
        for value in ['../perfil', '@', 'nome com espaço']:
            with self.assertRaises(ValueError):
                app.creator_name(value)
        for value in ['file:///etc/passwd', '--help', 'https://user:password@example.test/video']:
            with self.assertRaises(ValueError):
                app.validate_url(value)
        for value in ['2-1', '1-3', 'a-b', '-1-2']:
            with self.assertRaises(ValueError):
                app.cut_bounds(value, 2)
        (self.root / 'fila.txt').write_text('# comentário\n\n')
        self.assertEqual(app.download(self.args()), 0)
        with app.lock(self.root / '.download.lock'):
            with self.assertRaises(ValueError):
                app.download(self.args())

    def test_real_ytdlp_http_download_and_edit(self):
        source = self.sample(audio=True)
        source.rename(self.root / 'sample.mp4')
        class QuietHandler(http.server.SimpleHTTPRequestHandler):
            def log_message(self, *args):
                pass
        server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(QuietHandler, directory=str(self.root)))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        url = f'http://127.0.0.1:{server.server_port}/sample.mp4'
        (self.root / 'fila.txt').write_text(f'@teste | {url} | download real | teste / real | 0-1\n')
        self.assertEqual(app.download(self.args()), 0)
        outputs = list((self.root / 'prontos').glob('*.mp4'))
        self.assertEqual(len(outputs), 1)
        self.assert_video(outputs[0], 3)
        self.assertEqual(app.download(self.args()), 0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
