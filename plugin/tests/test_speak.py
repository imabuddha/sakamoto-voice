"""Unit tests for plugin/scripts/speak.py, without the network or speech:

    python3 -m unittest discover -s plugin/tests

The settings, the pid file, and the log go to a temporary folder, never ~/.config. The one test
with sockets uses the loopback interface and is skipped where it can't listen.
"""
import base64, io, json, os, socket, sys, tempfile, threading, unittest, wave
from contextlib import redirect_stdout
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))
import speak  # noqa: E402

BROWSE = """Browsing for _sakamotovoice._tcp.local.
DATE: ---Mon 12 Oct 2026---
11:40:52.806  ...STARTING...
Timestamp     A/R    Flags  if Domain               Service Type         Instance Name
11:40:52.806  Add        3  15 local.               _sakamotovoice._tcp. iPhone
11:40:52.806  Add        3  14 local.               _sakamotovoice._tcp. iPhone
11:40:52.807  Add        2  15 local.               _sakamotovoice._tcp. Example iPhone
11:40:52.808  Add        2  15 local.               _companion-link._tcp. Living
11:40:53.100  Rmv        0  15 local.               _sakamotovoice._tcp. iPhone
"""

LOOKUP = """Lookup Example iPhone._sakamotovoice._tcp.local
DATE: ---Mon 12 Oct 2026---
11:41:00.835  ...STARTING...
11:41:00.836  Example\\032iPhone._sakamotovoice._tcp.local. can be reached at Example-iPhone.local.:47811 (interface 15)
"""


class Isolated(unittest.TestCase):
    """Points speak.py's files at a temporary folder."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        home = self.dir.name
        patches = {'HOME': home, 'CONFIG': os.path.join(home, 'config.json'),
                   'PIDFILE': os.path.join(home, 'speaker.pid'), 'LOG': os.path.join(home, 'speak.log')}
        for name, value in patches.items():
            p = mock.patch.object(speak, name, value)
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(self.dir.cleanup)

    def write_config(self, cfg):
        with open(speak.CONFIG, 'w') as f:
            json.dump(cfg, f)

    def read_config(self):
        with open(speak.CONFIG) as f:
            return json.load(f)

    def log_text(self):
        try:
            with open(speak.LOG) as f:
                return f.read()
        except FileNotFoundError:
            return ''


class ConfigTests(Isolated):
    def test_old_config_gets_the_new_defaults(self):
        self.write_config({'enabled': False, 'voice_en': 'Zoe (Premium)', 'rate': 200})
        cfg = speak.config()
        self.assertEqual(cfg['voice_en'], 'Zoe (Premium)')
        self.assertFalse(cfg['enabled'])
        self.assertEqual(cfg['output'], 'mac')
        self.assertEqual(cfg['phone_mode'], 'text')
        self.assertEqual(cfg['phone_token'], '')
        self.assertEqual(cfg['default_lang'], 'auto')

    def test_first_use_writes_the_defaults(self):
        cfg = speak.config()
        self.assertEqual(self.read_config(), cfg)
        self.assertEqual(cfg['output'], 'mac')

    def test_remember_keeps_other_changes(self):
        self.write_config({'output': 'both', 'phone_token': '123456'})
        speak.remember(phone='Example-iPhone.local:47811')
        cfg = self.read_config()
        self.assertEqual((cfg['output'], cfg['phone_token'], cfg['phone']),
                         ('both', '123456', 'Example-iPhone.local:47811'))


class LogTests(Isolated):
    def test_lines_and_rotation(self):
        speak.log('first\nline')
        self.assertTrue(self.log_text().endswith(' first line\n'))
        with mock.patch.object(speak, 'LOG_MAX', 100):
            for i in range(20):
                speak.log(f'entry {i}')
        self.assertTrue(os.path.exists(speak.LOG + '.1'))
        self.assertLess(os.path.getsize(speak.LOG), 200)
        self.assertIn('entry 19', self.log_text())

    def test_never_raises(self):
        with mock.patch.object(speak, 'HOME', '/dev/null/nowhere'), \
             mock.patch.object(speak, 'LOG', '/dev/null/nowhere/speak.log'):
            speak.log('lost')


class SegmentsTests(unittest.TestCase):
    """The same cases as the app's LanguageSplitterTests."""

    def runs(self, text):
        return [[lang, chunk] for lang, chunk in speak.segments(text)]

    def test_cases(self):
        cases = {
            'Hello there.': [['en', 'Hello there.']],
            'そうやで。': [['ja', 'そうやで。']],
            'Good heavens, Miss Sakamoto, you can talk! そうやで。':
                [['en', 'Good heavens, Miss Sakamoto, you can talk!'], ['ja', 'そうやで。']],
            'The word 囲碁 means Go.': [['en', 'The word'], ['ja', '囲碁'], ['en', 'means Go.']],
            '今日は 10 月 12 日です. Done': [['ja', '今日は 10 月 12 日です'], ['en', '. Done']],
            '3 時': [['en', '3'], ['ja', '時']],
            '「はい」.': [['ja', '「はい」']],
            '..., 。': [['ja', '。']],
            ' ; ': [],
            '': [],
            'Play ＡＢＣ and カタカナ!': [['en', 'Play'], ['ja', 'ＡＢＣ'], ['en', 'and'], ['ja', 'カタカナ'], ['en', '!']],
            '一\n二\nthree': [['ja', '一\n二'], ['en', 'three']],
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(self.runs(text), expected)


class VoiceRunsTests(unittest.TestCase):
    """default_lang and the voice markers 〔en〕 and 〔ja〕."""

    def runs(self, text, default='ja'):
        return [[lang, chunk] for lang, chunk in speak.voice_runs(text, default)]

    def test_the_phone_default_leaves_unmarked_text_to_the_phone(self):
        self.assertEqual(self.runs('The word 囲碁 means Go.', 'default'),
                         [['default', 'The word'], ['ja', '囲碁'], ['default', 'means Go.']])
        self.assertEqual([list(r) for r in speak.voice_runs('Hi 〔en〕there 〔ja〕friend.\n\nBye.')],
                         [['default', 'Hi'], ['en', 'there'], ['ja', 'friend.'], ['default', 'Bye.']])

    def test_default_ja_reads_everything(self):
        self.assertEqual(self.runs('The word 囲碁 means Go.'), [['ja', 'The word 囲碁 means Go.']])
        self.assertEqual(self.runs('Hello.\n\nそうやで。\n\nBye.'), [['ja', 'Hello.\n\nそうやで。\n\nBye.']])

    def test_default_en_is_by_script(self):
        self.assertEqual(self.runs('The word 囲碁 means Go.', 'en'),
                         [['en', 'The word'], ['ja', '囲碁'], ['en', 'means Go.']])

    def test_a_bad_default_is_the_phones(self):
        self.assertEqual(self.runs('Hello', 'fr'), [['default', 'Hello']])
        self.assertEqual(self.runs('Hello', None), [['default', 'Hello']])
        self.assertEqual(self.runs('Hello', 'auto'), [['default', 'Hello']])

    def test_en_marker_switches_until_the_next_marker(self):
        self.assertEqual(self.runs('Kyoko here. 〔en〕Moira here. 〔ja〕Kyoko again.'),
                         [['ja', 'Kyoko here.'], ['en', 'Moira here.'], ['ja', 'Kyoko again.']])

    def test_japanese_script_is_always_ja(self):
        self.assertEqual(self.runs('〔en〕The word 囲碁 means Go.'),
                         [['en', 'The word'], ['ja', '囲碁'], ['en', 'means Go.']])

    def test_ja_marker_with_default_en(self):
        self.assertEqual(self.runs('Plain. 〔ja〕Read by Kyoko.', 'en'),
                         [['en', 'Plain.'], ['ja', 'Read by Kyoko.']])

    def test_paragraph_end_resets_to_the_default(self):
        self.assertEqual(self.runs('〔en〕One,\nstill one.\n\nTwo.\n \nThree.'),
                         [['en', 'One,\nstill one.'], ['ja', 'Two.\n \nThree.']])
        self.assertEqual(self.runs('〔ja〕One.\n\nTwo.', 'en'), [['ja', 'One.'], ['en', 'Two.']])

    def test_markers_are_never_spoken(self):
        for text in ('〔en〕', '〔en〕〔ja〕', '〔ja〕 . ', '〔xx〕', '〔EN〕Hi', '〔 en 〕Hi'):
            with self.subTest(text=text):
                self.assertFalse(any('〔' in chunk or '〕' in chunk for _, chunk in speak.voice_runs(text)))
        self.assertEqual(self.runs('〔EN〕Hi'), [['en', 'Hi']])
        self.assertEqual(self.runs('〔 en 〕Hi'), [['en', 'Hi']])

    def test_unknown_markers_are_stripped_and_change_nothing(self):
        self.assertEqual(self.runs('〔en〕Hello 〔xx〕there.'), [['en', 'Hello there.']])
        self.assertEqual(self.runs('Hello 〔fr〕there.'), [['ja', 'Hello there.']])
        self.assertEqual(self.runs('Hello 〔fr〕there.', 'default'), [['default', 'Hello there.']])

    def test_bracketed_japanese_is_text(self):
        self.assertEqual(self.runs('〔en〕See 〔注〕 below.'), [['en', 'See'], ['ja', '〔注〕'], ['en', 'below.']])

    def test_punctuation_stays_with_its_neighbor(self):
        self.assertEqual(self.runs('〔en〕Go is 囲碁. 〔ja〕Yes.'), [['en', 'Go is'], ['ja', '囲碁. Yes.']])
        self.assertEqual(self.runs('〔en〕.'), [])

    def test_strip_markers(self):
        cases = {
            '〔en〕Hello 〔ja〕囲碁 〔xx〕friend.': 'Hello 囲碁 friend.',
            'Say 〔ja〕 hi.': 'Say hi.',
            '〔en〕 Line one\n〔ja〕Line two\n\n〔en〕': 'Line one\nLine two',
            'See 〔注〕.': 'See 〔注〕.',
            'No markers.': 'No markers.',
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(speak.strip_markers(text), expected)

    def test_prepare_uses_the_config(self):
        self.assertEqual(speak.prepare('Hi 〔en〕there', dict(speak.DEFAULTS, default_lang='ja')),
                         ('Hi there', [('ja', 'Hi'), ('en', 'there')], [('default', 'Hi'), ('en', 'there')]))
        self.assertEqual(speak.prepare('Hi 囲碁', dict(speak.DEFAULTS, default_lang='en')),
                         ('Hi 囲碁', [('en', 'Hi'), ('ja', '囲碁')], [('default', 'Hi'), ('ja', '囲碁')]))

    def test_prepare_auto_uses_the_system_language(self):
        for system in ('en', 'ja'):
            with self.subTest(system=system), mock.patch.object(speak, 'system_lang', return_value=system):
                _, mac, phone = speak.prepare('Hi 囲碁', dict(speak.DEFAULTS))
                self.assertEqual(mac, [('en', 'Hi'), ('ja', '囲碁')] if system == 'en' else [('ja', 'Hi 囲碁')])
                self.assertEqual(phone, [('default', 'Hi'), ('ja', '囲碁')])

    def test_mac_lang(self):
        with mock.patch.object(speak, 'system_lang', return_value='ja'):
            self.assertEqual(speak.mac_lang({'default_lang': 'en'}), 'en')
            self.assertEqual(speak.mac_lang({'default_lang': 'ja'}), 'ja')
            self.assertEqual(speak.mac_lang({'default_lang': 'auto'}), 'ja')
            self.assertEqual(speak.mac_lang({'default_lang': 'fr'}), 'ja')
            self.assertEqual(speak.mac_lang({}), 'ja')

    def test_system_lang_reads_apple_languages(self):
        cases = {'(\n    "en-US",\n    "ja-US"\n)\n': 'en', '(\n    "ja-JP",\n    "en-JP"\n)\n': 'ja',
                 '(\n    ja\n)\n': 'ja', '(\n    "de-DE"\n)\n': 'en', '': 'en'}
        for out, expected in cases.items():
            with self.subTest(out=out), mock.patch.object(speak.subprocess, 'run',
                                                          return_value=mock.Mock(stdout=out)):
                self.assertEqual(speak.system_lang(), expected)
        with mock.patch.object(speak.subprocess, 'run', side_effect=OSError('no defaults')):
            self.assertEqual(speak.system_lang(), 'en')

    def test_markers_survive_speakable(self):
        text = speak.speakable('**Bold** 〔en〕*English* here.\n\n- 〔en〕A list item')
        self.assertEqual(speak.voice_runs(text, 'ja'), [('ja', 'Bold'), ('en', 'English here.\n\nA list item')])


class DiscoveryParsingTests(unittest.TestCase):
    def test_browse(self):
        self.assertEqual(speak.parse_browse(BROWSE), ['Example iPhone'])

    def test_browse_other_service(self):
        self.assertEqual(speak.parse_browse(BROWSE, '_companion-link._tcp'), ['Living'])

    def test_browse_nothing(self):
        self.assertEqual(speak.parse_browse('DNSServiceBrowse failed -65563 (Service Not Running)\n'), [])

    def test_lookup(self):
        self.assertEqual(speak.parse_lookup(LOOKUP), 'Example-iPhone.local:47811')
        self.assertEqual(speak.parse_lookup('Lookup x._sakamotovoice._tcp.local\n'), '')

    def test_split_address(self):
        self.assertEqual(speak.split_address('Example-iPhone.local:47811'), ('Example-iPhone.local', 47811))
        self.assertEqual(speak.split_address('fe80::1:47811'), ('fe80::1', 47811))

    def test_normalize_code(self):
        self.assertEqual(speak.normalize_code('123456'), '123456')
        self.assertEqual(speak.normalize_code('123 456'), '123456')
        self.assertEqual(speak.normalize_code('123-456'), '123456')
        self.assertEqual(speak.normalize_code('12345'), '')
        self.assertEqual(speak.normalize_code('12345a'), '')
        self.assertEqual(speak.normalize_code(None), '')


class MessageTests(unittest.TestCase):
    def test_text(self):
        msg = json.loads(speak.message('123456', 'text', text='Hi 囲碁', runs=[('en', 'Hi'), ('ja', '囲碁')]))
        self.assertEqual(msg, {'token': '123456', 'kind': 'text', 'text': 'Hi 囲碁',
                               'lang_runs': [{'lang': 'en', 'text': 'Hi'}, {'lang': 'ja', 'text': '囲碁'}]})

    def test_audio(self):
        msg = json.loads(speak.message('1', 'audio', text='Hi', audio=b'\x00\x01m4a'))
        self.assertEqual(base64.b64decode(msg['audio_b64']), b'\x00\x01m4a')
        self.assertEqual((msg['kind'], msg['format'], msg['text']), ('audio', 'm4a', 'Hi'))

    def test_ping_is_minimal(self):
        self.assertEqual(json.loads(speak.message('1', 'ping')), {'token': '1', 'kind': 'ping'})

    def test_utf8_on_the_wire(self):
        self.assertIn('囲碁'.encode('utf-8'), speak.message('1', 'text', text='囲碁'))


class PayloadTests(Isolated):
    def test_text_mode(self):
        cfg = dict(speak.DEFAULTS, phone_token='123456')
        msg = json.loads(speak.phone_payload(cfg, 'Hi 囲碁', [('default', 'Hi'), ('ja', '囲碁')],
                                             [('ja', 'Hi 囲碁')], set()))
        self.assertEqual(msg['kind'], 'text')
        self.assertEqual(msg['lang_runs'], [{'lang': 'default', 'text': 'Hi'}, {'lang': 'ja', 'text': '囲碁'}])

    def test_audio_mode(self):
        cfg = dict(speak.DEFAULTS, phone_token='123456', phone_mode='audio')
        with mock.patch.object(speak, 'render_audio', return_value=b'AAC') as render:
            msg = json.loads(speak.phone_payload(cfg, 'Hi', [('default', 'Hi')], [('ja', 'Hi')], set()))
        self.assertEqual((msg['kind'], base64.b64decode(msg['audio_b64'])), ('audio', b'AAC'))
        self.assertEqual(render.call_args[0][0], [('ja', 'Hi')])     # audio is in the Mac's voices

    def test_audio_mode_falls_back_to_text(self):
        cfg = dict(speak.DEFAULTS, phone_token='123456', phone_mode='audio')
        with mock.patch.object(speak, 'render_audio', return_value=None):
            msg = json.loads(speak.phone_payload(cfg, 'Hi', [('default', 'Hi')], [('ja', 'Hi')], set()))
        self.assertEqual((msg['kind'], msg['lang_runs']), ('text', [{'lang': 'default', 'text': 'Hi'}]))
        self.assertIn('sending text instead', self.log_text())

    def test_say_command(self):
        cfg = dict(speak.DEFAULTS, voice_en='Moira', voice_ja='Kyoko', rate=180, device='Speaker')
        self.assertEqual(speak.say_command(cfg, {'Moira', 'Kyoko'}, 'en'),
                         ['say', '-v', 'Moira', '-r', '180', '-a', 'Speaker'])
        self.assertEqual(speak.say_command(cfg, {'Moira', 'Kyoko'}, 'ja', play=False),
                         ['say', '-v', 'Kyoko', '-r', '180'])
        self.assertEqual(speak.say_command(dict(speak.DEFAULTS), set(), 'en'), ['say'])


class WavTests(unittest.TestCase):
    def make(self, path, frames, rate=22050):
        with wave.open(path, 'wb') as w:
            w.setparams((1, 2, rate, 0, 'NONE', 'not compressed'))
            w.writeframes(b'\x01\x00' * frames)

    def test_concat_with_gaps(self):
        with tempfile.TemporaryDirectory() as d:
            a, b, c, odd = (os.path.join(d, n) for n in ('a.wav', 'b.wav', 'c.wav', 'odd.wav'))
            self.make(a, 1000)
            self.make(b, 500)
            self.make(odd, 300, rate=44100)          # a different format is skipped
            speak.concat_wavs([a, odd, b], c, gap=0.1)
            with wave.open(c) as w:
                self.assertEqual(w.getframerate(), 22050)
                self.assertEqual(w.getnframes(), 1000 + 2205 + 500)


class ServerStub:
    """A stand-in phone on the loopback interface: answers each connection with `reply`."""

    def __init__(self, reply):
        self.reply = reply
        self.received = []
        self.sock = socket.socket()
        try:
            self.sock.bind(('127.0.0.1', 0))
            self.sock.listen()
        except OSError:
            self.sock.close()
            raise
        self.address = f'127.0.0.1:{self.sock.getsockname()[1]}'
        self.thread = threading.Thread(target=self.serve, daemon=True)
        self.thread.start()

    def serve(self):
        while True:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            with conn:
                data = b''
                while chunk := conn.recv(65536):
                    data += chunk
                self.received.append(json.loads(data))
                conn.sendall(json.dumps(self.reply).encode() + b'\n')

    def close(self):
        self.sock.close()


def closed_port():
    s = socket.socket()
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()
    return f'127.0.0.1:{port}'


class SendTests(Isolated):
    def setUp(self):
        super().setUp()
        try:
            self.phone = ServerStub({'ok': True, 'app': 'Sakamoto Voice', 'version': 'test'})
        except OSError as e:
            self.skipTest(f'cannot listen here: {e}')
        self.addCleanup(self.phone.close)

    def test_exchange(self):
        ack = speak.exchange(self.phone.address, speak.message('123456', 'text', text='Hi'))
        self.assertTrue(ack['ok'])
        self.assertEqual(self.phone.received, [{'token': '123456', 'kind': 'text', 'text': 'Hi'}])

    def test_exchange_large(self):
        audio = os.urandom(2_000_000)
        speak.exchange(self.phone.address, speak.message('1', 'audio', audio=audio))
        self.assertEqual(base64.b64decode(self.phone.received[0]['audio_b64']), audio)

    def test_send_to_the_remembered_phone(self):
        self.write_config({'phone_token': '123456', 'phone': self.phone.address})
        with mock.patch.object(speak, 'find_phone') as find:
            ack = speak.send_to_phone(speak.message('123456', 'ping'))
        self.assertTrue(ack['ok'])
        find.assert_not_called()

    def test_a_failed_send_finds_the_phone_again(self):
        self.write_config({'phone_token': '123456', 'phone': closed_port()})
        with mock.patch.object(speak, 'find_phone', return_value=('iPhone', self.phone.address)) as find:
            ack = speak.send_to_phone(speak.message('123456', 'ping'))
        self.assertTrue(ack['ok'])
        find.assert_called_once_with('123456')
        cfg = self.read_config()
        self.assertEqual((cfg['phone'], cfg['phone_name']), (self.phone.address, 'iPhone'))
        self.assertIn('looking for it again', self.log_text())

    def test_no_phone_is_logged_not_raised(self):
        self.write_config({'phone_token': '123456', 'phone': closed_port()})
        with mock.patch.object(speak, 'find_phone', return_value=None):
            self.assertIsNone(speak.send_to_phone(speak.message('123456', 'ping')))
        self.assertIn('no phone with Sakamoto Voice answered', self.log_text())

    def test_unpaired(self):
        self.assertIsNone(speak.send_to_phone(speak.message('', 'ping')))
        self.assertIn('not paired', self.log_text())

    def test_find_phone_pings_each_until_one_accepts(self):
        refusing = ServerStub({'ok': False, 'error': 'bad token'})
        self.addCleanup(refusing.close)
        addresses = {'Other': refusing.address, 'Mine': self.phone.address}
        with mock.patch.object(speak, 'browse', return_value=['Gone', 'Other', 'Mine']), \
             mock.patch.object(speak, 'lookup', side_effect=lambda name: addresses.get(name, '')):
            self.assertEqual(speak.find_phone('123456'), ('Mine', self.phone.address))
        self.assertEqual(refusing.received[0]['kind'], 'ping')
        self.assertIn("'Gone' did not resolve", self.log_text())

    def test_deliver_never_raises(self):
        cfg = dict(speak.DEFAULTS, phone_token='123456')
        with mock.patch.object(speak, 'send_to_phone', side_effect=RuntimeError('boom')):
            speak.deliver_to_phone(cfg, 'Hi', [('default', 'Hi')], [('en', 'Hi')], set())
        self.assertIn('RuntimeError: boom', self.log_text())


class CommandTests(Isolated):
    def run_main(self, *args):
        out = io.StringIO()
        with mock.patch.object(sys, 'argv', ['speak.py', *args]), redirect_stdout(out):
            code = speak.main()
        return code, out.getvalue()

    def test_output(self):
        self.assertEqual(self.run_main('output', 'both')[0], 0)
        self.assertEqual(self.read_config()['output'], 'both')
        self.assertEqual(self.run_main('output', 'radio')[0], 2)
        self.assertEqual(self.read_config()['output'], 'both')

    def test_phone_mode(self):
        self.assertEqual(self.run_main('phone-mode', 'audio')[0], 0)
        self.assertEqual(self.read_config()['phone_mode'], 'audio')
        self.assertEqual(self.run_main('phone-mode', 'video')[0], 2)

    def test_pair_stores_the_code_and_the_phone(self):
        with mock.patch.object(speak, 'find_phone', return_value=('iPhone', 'iPhone.local:47811')):
            code, out = self.run_main('pair', '123', '456')
        self.assertEqual(code, 0)
        cfg = self.read_config()
        self.assertEqual((cfg['phone_token'], cfg['phone'], cfg['phone_name']),
                         ('123456', 'iPhone.local:47811', 'iPhone'))
        self.assertIn('speak.py output phone', out)

    def test_pair_with_a_bad_code(self):
        code, out = self.run_main('pair', '12345')
        self.assertEqual(code, 1)
        self.assertEqual(self.read_config()['phone_token'], '')

    def test_pair_with_no_phone_keeps_the_code(self):
        with mock.patch.object(speak, 'find_phone', return_value=None):
            code, out = self.run_main('pair', '654321')
        self.assertEqual(code, 1)
        self.assertEqual(self.read_config()['phone_token'], '654321')
        self.assertIn('No phone answered', out)

    def test_phone_test_unpaired(self):
        code, out = self.run_main('phone-test')
        self.assertEqual(code, 1)
        self.assertIn('Not paired', out)

    def test_phone_test_bad_token(self):
        self.write_config({'phone_token': '123456'})
        with mock.patch.object(speak, 'send_to_phone', return_value={'ok': False, 'error': 'bad token'}), \
             mock.patch.object(speak, 'installed_voices', return_value=set()):
            code, out = self.run_main('phone-test', 'Hello')
        self.assertEqual(code, 1)
        self.assertIn('Pair again', out)

    def test_stop_tells_the_phone(self):
        self.write_config({'output': 'phone', 'phone': 'iPhone.local:47811', 'phone_token': '123456'})
        with mock.patch.object(speak, 'exchange') as exchange, mock.patch.object(speak, 'stop_speaker'):
            self.run_main('stop')
        address, payload = exchange.call_args[0]
        self.assertEqual(address, 'iPhone.local:47811')
        self.assertEqual(json.loads(payload)['kind'], 'stop')

    def test_stop_leaves_the_phone_alone_on_mac_output(self):
        self.write_config({'output': 'mac', 'phone': 'iPhone.local:47811', 'phone_token': '123456'})
        with mock.patch.object(speak, 'exchange') as exchange, mock.patch.object(speak, 'stop_speaker'):
            self.run_main('stop')
        exchange.assert_not_called()


class SpeakerTests(Isolated):
    """The detached speaker's routing, with `say` and the phone mocked."""

    def run_speaker(self, cfg, text='Hello 囲碁', voices=frozenset(), system='en'):
        self.write_config(cfg)
        fd, path = tempfile.mkstemp(dir=self.dir.name)
        with os.fdopen(fd, 'w') as f:
            f.write(text)
        with mock.patch.object(speak, 'installed_voices', return_value=set(voices)), \
             mock.patch.object(speak.subprocess, 'run') as run, \
             mock.patch.object(speak, 'deliver_to_phone') as deliver, \
             mock.patch.object(speak, 'system_lang', return_value=system):
            speak.speak(path)
        self.assertFalse(os.path.exists(path))
        return run, deliver

    def spoken(self, run):
        return [c[0][0][-1] for c in run.call_args_list]

    def test_mac(self):
        run, deliver = self.run_speaker({'output': 'mac', 'default_lang': 'en'})
        self.assertEqual(self.spoken(run), ['Hello', '囲碁'])
        deliver.assert_not_called()

    def test_mac_ja_is_one_japanese_voice(self):
        run, deliver = self.run_speaker({'output': 'mac', 'default_lang': 'ja'})
        self.assertEqual(self.spoken(run), ['Hello 囲碁'])

    def test_mac_auto_follows_the_system_language(self):
        run, _ = self.run_speaker({'output': 'mac'})
        self.assertEqual(self.spoken(run), ['Hello', '囲碁'])
        run, _ = self.run_speaker({'output': 'mac'}, system='ja')
        self.assertEqual(self.spoken(run), ['Hello 囲碁'])

    def test_mac_markers(self):
        run, _ = self.run_speaker({'output': 'mac', 'voice_en': 'Moira', 'voice_ja': 'Kyoko', 'default_lang': 'ja'},
                                  'Hello 〔en〕there 囲碁.\n\nBack to Kyoko.', voices={'Moira', 'Kyoko'})
        self.assertEqual([c[0][0][1:] for c in run.call_args_list],
                         [['-v', 'Kyoko', 'Hello'], ['-v', 'Moira', 'there'], ['-v', 'Kyoko', '囲碁.\n\nBack to Kyoko.']])

    def test_phone(self):
        run, deliver = self.run_speaker({'output': 'phone', 'default_lang': 'ja'})
        run.assert_not_called()
        cfg, text, runs, mac_runs, _ = deliver.call_args[0]
        self.assertEqual(text, 'Hello 囲碁')
        self.assertEqual(runs, [('default', 'Hello'), ('ja', '囲碁')])    # the phone's default decides
        self.assertEqual(mac_runs, [('ja', 'Hello 囲碁')])                  # for audio rendered here

    def test_phone_gets_the_text_without_markers(self):
        _, deliver = self.run_speaker({'output': 'phone'}, '〔en〕Hello 〔ja〕囲碁 〔xx〕friend.')
        cfg, text, runs, _, _ = deliver.call_args[0]
        self.assertEqual(text, 'Hello 囲碁 friend.')
        self.assertEqual(runs, [('en', 'Hello'), ('ja', '囲碁 friend.')])

    def test_both(self):
        run, deliver = self.run_speaker({'output': 'both', 'default_lang': 'en'})
        self.assertEqual(run.call_count, 2)
        deliver.assert_called_once()

    def test_unknown_output_is_mac(self):
        run, deliver = self.run_speaker({'output': 'radio', 'default_lang': 'en'})
        self.assertEqual(run.call_count, 2)
        deliver.assert_not_called()

    def test_app_both(self):
        with mock.patch.object(speak, 'app_read', return_value=True):
            run, deliver = self.run_speaker({'output': 'app-both', 'default_lang': 'en'})
        run.assert_not_called()                  # the app speaks on the Mac
        deliver.assert_called_once()             # and the phone gets the text
        with mock.patch.object(speak, 'app_read', return_value=False):
            run, deliver = self.run_speaker({'output': 'app-both', 'default_lang': 'en'})
        self.assertEqual(run.call_count, 2)      # the Mac's own voice instead
        deliver.assert_called_once()

    def test_app_phone_hands_over_to_app_phone(self):
        with mock.patch.object(speak, 'app_phone') as app_phone:
            run, deliver = self.run_speaker({'output': 'app-phone', 'default_lang': 'ja'}, '〔en〕Hello 囲碁')
        run.assert_not_called()                  # the Mac says nothing itself
        deliver.assert_not_called()
        cfg, raw, text, runs, mac_runs, voices = app_phone.call_args[0]
        self.assertEqual((cfg['output'], raw, text), ('app-phone', '〔en〕Hello 囲碁', 'Hello 囲碁'))
        self.assertEqual(runs, [('en', 'Hello'), ('ja', '囲碁')])
        self.assertEqual(mac_runs, [('en', 'Hello'), ('ja', '囲碁')])

    def test_app_phone_with_nothing_to_say(self):
        with mock.patch.object(speak, 'app_phone') as app_phone:
            run, deliver = self.run_speaker({'output': 'app-phone'}, '🙂')
        app_phone.assert_not_called()
        run.assert_not_called()


# ---- output app-phone ------------------------------------------------------------------------

FAKE_TAP = r'''#!/bin/sh
# A stand-in for app-voice-tap: records its arguments and standard input, then acts out $MODE.
printf '%s\n' "$@" > "$DIR/args"
cat > "$DIR/stdin"
case "$MODE" in
  ok)      echo ready; echo "streamed 3.2 s to phone:47811; the app went quiet"; exit 0 ;;
  refused) echo "the phone at phone:47811 refused the stream: bad token"; exit 4 ;;
  silent)  echo ready; echo "no sound from the Claude app within 10.0 s"; exit 6 ;;
  hang)    echo ready; exec sleep 30 ;;
  mute)    exec sleep 30 ;;
esac
'''


class TapTests(Isolated):
    """The Tap wrapper with a shell script standing in for app-voice-tap (no audio)."""

    def setUp(self):
        super().setUp()
        self.tool = os.path.join(self.dir.name, 'app-voice-tap')
        with open(self.tool, 'w') as f:
            f.write(FAKE_TAP)
        os.chmod(self.tool, 0o755)

    def tap(self, mode, text='Hello 囲碁'):
        with mock.patch.dict(os.environ, {'MODE': mode, 'DIR': self.dir.name}):
            return speak.Tap(self.tool, 'phone.local:47811', '123456', text)

    def read(self, name):
        with open(os.path.join(self.dir.name, name), encoding='utf-8') as f:
            return f.read()

    def test_a_reading(self):
        tap = self.tap('ok')
        self.assertTrue(tap.wait_ready())
        self.assertEqual(tap.finish(timeout=5), (0, 'streamed 3.2 s to phone:47811; the app went quiet'))
        self.assertEqual(self.read('args').split('\n')[:-1],
                         ['--to', 'phone.local:47811', '--token', '123456', '--mute', '--text-stdin',
                          '--wait-start', str(speak.TAP_WAIT_START), '--max-seconds', str(speak.TAP_MAX_SECONDS)])
        self.assertEqual(self.read('stdin'), 'Hello 囲碁')

    def test_refused_before_ready(self):
        tap = self.tap('refused')
        self.assertFalse(tap.wait_ready(timeout=5))
        self.assertEqual(tap.stop(), 4)
        self.assertEqual(tap.last_line(), 'the phone at phone:47811 refused the stream: bad token')

    def test_no_sound(self):
        tap = self.tap('silent')
        self.assertTrue(tap.wait_ready())
        self.assertEqual(tap.finish(timeout=5), (speak.TAP_NO_SOUND, 'no sound from the Claude app within 10.0 s'))

    def test_never_ready_is_stopped(self):
        tap = self.tap('mute')
        self.assertFalse(tap.wait_ready(timeout=0.3))
        self.assertLess(tap.stop(), 0)          # terminated
        self.assertEqual(tap.last_line(), 'no output')

    def test_finish_stops_it_when_it_runs_too_long(self):
        tap = self.tap('hang')
        self.assertTrue(tap.wait_ready())
        status, line = tap.finish(timeout=0.3)
        self.assertLess(status, 0)
        self.assertEqual(line, 'no output')


class TapPathTests(Isolated):
    def test_the_config_first_then_local_bin_then_path(self):
        files = {'/opt/tap', os.path.expanduser('~/.local/bin/app-voice-tap'), '/usr/bin/app-voice-tap'}
        with mock.patch.object(speak.os.path, 'isfile', side_effect=lambda p: p in files), \
             mock.patch.object(speak.os, 'access', return_value=True), \
             mock.patch.object(speak.shutil, 'which', return_value='/usr/bin/app-voice-tap'):
            self.assertEqual(speak.tap_path({'app_voice_tap': '/opt/tap'}), '/opt/tap')
            self.assertEqual(speak.tap_path({}), os.path.expanduser('~/.local/bin/app-voice-tap'))
            files.discard(os.path.expanduser('~/.local/bin/app-voice-tap'))
            self.assertEqual(speak.tap_path({'app_voice_tap': '/gone'}), '/usr/bin/app-voice-tap')

    def test_the_checkout_bin(self):
        here = os.path.dirname(os.path.abspath(speak.__file__))
        built = os.path.normpath(os.path.join(here, '..', '..', 'bin', 'app-voice-tap'))
        with mock.patch.object(speak.os.path, 'isfile', side_effect=lambda p: os.path.normpath(p) == built), \
             mock.patch.object(speak.os, 'access', return_value=True), \
             mock.patch.object(speak.shutil, 'which', return_value=None):
            self.assertEqual(speak.tap_path({}), built)

    def test_not_built(self):
        with mock.patch.object(speak.os.path, 'isfile', return_value=False), \
             mock.patch.object(speak.shutil, 'which', return_value=None):
            self.assertIsNone(speak.tap_path({}))


class FakeTap:
    """Stands in for speak.Tap (calling it "starts" it): `ready`, then `status` and `line`."""

    def __init__(self, ready=True, status=0, line='streamed 3.2 s to phone:47811; the app went quiet'):
        self.ready, self.status, self.line = ready, status, line
        self.stopped = False

    def __call__(self, path, address, token, text):
        self.args = (path, address, token, text)
        return self

    def wait_ready(self):
        return self.ready

    def finish(self, timeout):
        return self.status, self.line

    def stop(self):
        self.stopped = True
        return self.status

    def last_line(self):
        return self.line


class AppPhoneTests(Isolated):
    """output app-phone's choices, with the tool, the click, and the phone mocked."""

    CFG = dict(speak.DEFAULTS, output='app-phone', phone_token='123456', phone='old.local:47811')

    def run_app_phone(self, tap=None, clicked=True, ping={'ok': True}, path='/bin/app-voice-tap', cfg=None,
                      phone_now='Example-iPhone.local:47811'):
        cfg = cfg or dict(self.CFG)
        self.write_config(dict(cfg, phone=phone_now))       # as send_to_phone may have found it again
        tap = tap or FakeTap()
        with mock.patch.object(speak, 'tap_path', return_value=path), \
             mock.patch.object(speak, 'Tap', tap), \
             mock.patch.object(speak, 'send_to_phone', return_value=ping) as send, \
             mock.patch.object(speak, 'app_read', return_value=clicked) as click, \
             mock.patch.object(speak, 'deliver_to_phone') as deliver:
            speak.app_phone(cfg, 'Hello 囲碁', 'Hello 囲碁', [('default', 'Hello'), ('ja', '囲碁')], [('en', 'Hello')], set())
        return tap, send, click, deliver

    def assert_text_fallback(self, deliver):
        cfg, text, runs, _, _ = deliver.call_args[0]
        self.assertEqual((cfg['phone_mode'], text, runs), ('text', 'Hello 囲碁', [('default', 'Hello'), ('ja', '囲碁')]))

    def test_the_apps_voice_is_streamed(self):
        tap, send, click, deliver = self.run_app_phone()
        self.assertEqual(json.loads(send.call_args[0][0])['kind'], 'ping')
        self.assertEqual(tap.args, ('/bin/app-voice-tap', 'Example-iPhone.local:47811', '123456', 'Hello 囲碁'))
        self.assertLessEqual(click.call_args.kwargs['delay'], speak.APP_READ_DELAY)   # less the time spent
        deliver.assert_not_called()
        self.assertIn('app-phone: streamed 3.2 s', self.log_text())

    def test_debugger_off_sends_the_text(self):
        tap, _, _, deliver = self.run_app_phone(clicked=False)
        self.assertTrue(tap.stopped)
        self.assert_text_fallback(deliver)
        self.assertIn("debugger is off", self.log_text())

    def test_a_tap_that_does_not_start_sends_the_text(self):
        tap, _, click, deliver = self.run_app_phone(FakeTap(ready=False, status=3, line='System Audio Recording is off'))
        click.assert_not_called()
        self.assertTrue(tap.stopped)
        self.assert_text_fallback(deliver)
        self.assertIn('did not start: System Audio Recording is off', self.log_text())

    def test_no_sound_sends_the_text(self):
        _, _, _, deliver = self.run_app_phone(FakeTap(status=speak.TAP_NO_SOUND, line='no sound'))
        self.assert_text_fallback(deliver)

    def test_not_built_sends_the_text(self):
        _, send, click, deliver = self.run_app_phone(path=None)
        send.assert_not_called()
        click.assert_not_called()
        self.assert_text_fallback(deliver)
        self.assertIn('mac/build.sh', self.log_text())

    def test_no_phone_reads_nothing_aloud(self):
        tap, _, click, deliver = self.run_app_phone(ping=None)
        click.assert_not_called()
        deliver.assert_not_called()
        self.assertFalse(hasattr(tap, 'args'))
        self.assertIn('the phone did not answer (unreachable)', self.log_text())

    def test_a_refused_ping_reads_nothing_aloud(self):
        _, _, click, deliver = self.run_app_phone(ping={'ok': False, 'error': 'bad token'})
        click.assert_not_called()
        deliver.assert_not_called()
        self.assertIn('(bad token)', self.log_text())

    def test_a_failure_mid_stream_is_only_logged(self):
        _, _, _, deliver = self.run_app_phone(FakeTap(status=4, line='sending to the phone failed'))
        deliver.assert_not_called()
        self.assertIn('status 4: sending to the phone failed', self.log_text())

    def test_unpaired(self):
        _, send, click, deliver = self.run_app_phone(cfg=dict(self.CFG, phone_token=''))
        send.assert_not_called()
        click.assert_not_called()
        deliver.assert_not_called()
        self.assertIn('not paired', self.log_text())


class AppPhoneCommandTests(Isolated):
    run_main = CommandTests.run_main

    def test_output_app_phone(self):
        self.write_config({'phone_token': '123456'})
        with mock.patch.object(speak, 'tap_path', return_value='/bin/app-voice-tap'):
            code, out = self.run_main('output', 'app-phone')
        self.assertEqual(code, 0)
        self.assertEqual(self.read_config()['output'], 'app-phone')
        self.assertIn("in the Claude app's own voice, streamed live while the Mac stays silent", out)
        self.assertNotIn('pair', out)
        self.assertNotIn('mac/build.sh', out)

    def test_output_app_phone_says_what_is_missing(self):
        with mock.patch.object(speak, 'tap_path', return_value=None):
            code, out = self.run_main('output', 'app-phone')
        self.assertEqual(code, 0)
        self.assertIn('sakamoto pair CODE', out)
        self.assertIn('run mac/build.sh', out)

    def test_stop_tells_the_phone_in_app_phone_mode(self):
        self.write_config({'output': 'app-phone', 'phone': 'iPhone.local:47811', 'phone_token': '123456'})
        with mock.patch.object(speak, 'exchange') as exchange, mock.patch.object(speak, 'stop_speaker'):
            self.run_main('stop')
        self.assertEqual(json.loads(exchange.call_args[0][1])['kind'], 'stop')


if __name__ == '__main__':
    unittest.main()


class ReadKeyAndDevHandoff(unittest.TestCase):
    """The key app-read.mjs matches a response by, and dev_path's handoff."""

    def test_read_key(self):
        self.assertEqual(speak.read_key('15:44 **The page width:** done.'), '1544thepagewidthdone')
        self.assertEqual(speak.read_key('See [the repo](https://x.example/a) ![i](p.png) now'), 'seethereponow')
        self.assertEqual(speak.read_key('〔ja〕囲碁は楽しい'), 'ja囲碁は楽しい')
        self.assertEqual(len(speak.read_key('a' * 100)), 40)

    def test_dev_handoff_execs_the_checkout(self):
        with tempfile.TemporaryDirectory() as dev:
            os.makedirs(os.path.join(dev, 'scripts'))
            target = os.path.join(dev, 'scripts', 'speak.py')
            open(target, 'w').close()
            with mock.patch.object(speak, 'config', return_value={'dev_path': dev}), \
                 mock.patch.dict(os.environ, {}, clear=False), \
                 mock.patch.object(speak.os, 'execv') as execv:
                os.environ.pop('SAKAMOTO_DEV', None)
                speak.dev_handoff()
            self.assertEqual(execv.call_args[0][1][1], target)

    def test_dev_handoff_only_once_and_not_when_unset(self):
        with mock.patch.object(speak.os, 'execv') as execv:
            with mock.patch.object(speak, 'config', return_value={'dev_path': ''}):
                speak.dev_handoff()
            with mock.patch.object(speak, 'config', return_value={'dev_path': '/nonexistent'}):
                speak.dev_handoff()
            with mock.patch.object(speak, 'config', return_value={'dev_path': os.path.dirname(os.path.dirname(speak.__file__))}):
                speak.dev_handoff()          # this very copy
        execv.assert_not_called()
