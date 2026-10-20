"""Regressões e integração local real com FFmpeg, ffprobe e yt-dlp."""
import functools
import http.server
import json
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
        output = app.edit(source, '@parceiro', 'Legenda: "teste" 100%', "olha: 'isso' 100% / %{n}", '0.5-1.5')
        self.assert_video(output, 3)
        self.assertIn('Créditos: @parceiro', output.with_suffix('.txt').read_text())
        with self.assertRaises(ValueError):
            app.edit(source, '@parceiro', cut='1-7')
        self.assertTrue(output.exists())

    def test_silent_video(self):
        output = app.edit(self.sample(), '@parceiro')
        self.assert_video(output, 4)

    def args(self):
        # Reutiliza o parser público sem depender do main.
        import argparse
        return argparse.Namespace(url=None, creator=None, caption='', hook='', cut='', queue=str(self.root / 'fila.txt'), cookies_browser=None)

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
