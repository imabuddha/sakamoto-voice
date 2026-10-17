"""Unit tests for plugin/scripts/speak.py, without the network or speech:

    python3 -m unittest discover -s plugin/tests

The settings, the pid file, and the log go to a temporary folder, never ~/.config. The tests
with a stand-in phone use the loopback interface and are skipped where they can't listen.
"""
import base64, io, json, os, socket, sys, tempfile, threading, time, unittest, wave
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
                   'PIDFILE': os.path.join(home, 'speaker.pid'), 'LOG': os.path.join(home, 'speak.log'),
                   'PROMPTED': os.path.join(home, 'prompted'), 'RESPONDED': os.path.join(home, 'responded'),
                   'RECORDINGS': os.path.join(home, 'recordings'),
                   'APP_READING': os.path.join(home, 'app-reading'),
                   'LAST_PROMPT': os.path.join(home, 'last-prompt')}
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
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        port = s.getsockname()[1]
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


class AppReadingAndHushTests(Isolated):
    """The app-reading note Sakamoto Eyes watches while the Claude app reads, and barge-in's hush."""

    run_main = CommandTests.run_main

    def click(self, returncode, text='06:40 The relay is on.'):
        done = mock.Mock(returncode=returncode, stdout='clicked' if returncode == 0 else 'no Read aloud button',
                         stderr='')
        with mock.patch.object(speak.shutil, 'which', return_value='/usr/local/bin/node'), \
             mock.patch.object(speak.subprocess, 'run', return_value=done):
            return speak.app_read(text, delay=0)

    def reading(self):
        with open(speak.APP_READING, encoding='utf-8') as f:
            return json.load(f)

    def test_a_click_notes_the_reading(self):
        before = speak.time.time()
        self.assertTrue(self.click(0, '〔en〕06:40 The relay is on, so every reply gets its own block.'))
        note = self.reading()
        self.assertEqual(note['text'], '06:40 The relay is on, so every reply gets its own block.')
        self.assertGreaterEqual(note['started'], round(before, 3) - 0.001)
        self.assertGreater(note['ends'], note['started'] + 4)

    def test_no_click_no_note(self):
        self.assertFalse(self.click(1))
        self.assertFalse(os.path.exists(speak.APP_READING))

    def test_reading_seconds(self):
        twelve = 'Hello there, this is a test of twelve words in one sentence.'
        self.assertAlmostEqual(speak.reading_seconds(twelve), speak.READ_LEAD + 12 / speak.READ_WORDS_PER_SECOND)
        self.assertAlmostEqual(speak.reading_seconds('はい、今日は晴れですよ。'),
                               speak.READ_LEAD + 10 / speak.READ_JA_PER_SECOND)
        # Code isn't read, nor are markers.
        self.assertAlmostEqual(speak.reading_seconds('〔en〕Done. ```x = 1```'),
                               speak.READ_LEAD + 3 / speak.READ_WORDS_PER_SECOND)

    def test_hush_silences_everything_and_logs_a_barge_in(self):
        self.write_config({'output': 'phone', 'phone': 'iPhone.local:47811', 'phone_token': '123456'})
        with open(speak.PIDFILE, 'w') as f:
            f.write('424242')
        speak.note_app_reading('Reading this.')
        with mock.patch.object(speak, 'exchange') as exchange, mock.patch.object(speak.os, 'killpg') as killpg:
            code, _ = self.run_main('hush')
        self.assertEqual(code, 0)
        killpg.assert_called_once_with(424242, speak.signal.SIGTERM)
        self.assertFalse(os.path.exists(speak.PIDFILE))
        self.assertFalse(os.path.exists(speak.APP_READING))
        self.assertEqual(json.loads(exchange.call_args[0][1])['kind'], 'stop')
        self.assertIn('barge-in', self.log_text())
        self.assertFalse(os.path.exists(speak.PROMPTED))      # not a prompt

    def test_stop_and_the_next_response_remove_the_note(self):
        speak.note_app_reading('Reading this.')
        with mock.patch.object(speak, 'hook_prompt', return_value=''):
            self.run_main('stop')
        self.assertFalse(os.path.exists(speak.APP_READING))
        speak.note_app_reading('Reading this.')
        with mock.patch.object(speak.subprocess, 'Popen'):
            speak.launch('The next response.')
        self.assertFalse(os.path.exists(speak.APP_READING))


class SpeakerTests(Isolated):
    """The detached speaker's routing, with `say` and the phone mocked."""

    def run_speaker(self, cfg, text='Hello 囲碁', voices=frozenset(), system='en', prompted=True, turn=None):
        self.write_config(cfg)
        fd, path = tempfile.mkstemp(dir=self.dir.name)
        with os.fdopen(fd, 'w') as f:
            f.write(text)
        with mock.patch.object(speak, 'installed_voices', return_value=set(voices)), \
             mock.patch.object(speak.subprocess, 'run') as run, \
             mock.patch.object(speak, 'deliver_to_phone') as deliver, \
             mock.patch.object(speak, 'system_lang', return_value=system):
            speak.speak(path, prompted=prompted, turn=turn)
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

    def test_app_both_streams_without_muting(self):
        with mock.patch.object(speak, 'app_phone', return_value=None) as app_phone:
            run, deliver = self.run_speaker({'output': 'app-both', 'default_lang': 'en'})
        self.assertTrue(app_phone.call_args.kwargs['both'])
        run.assert_not_called()
        deliver.assert_not_called()

    def test_app_both_before_the_click_falls_back_to_the_app_here_and_text_there(self):
        with mock.patch.object(speak, 'app_phone', return_value='before-click'), \
             mock.patch.object(speak, 'app_read', return_value=True):
            run, deliver = self.run_speaker({'output': 'app-both', 'default_lang': 'en'})
        run.assert_not_called()                  # the app speaks on the Mac
        deliver.assert_called_once()             # and the phone gets the text
        with mock.patch.object(speak, 'app_phone', return_value='before-click'), \
             mock.patch.object(speak, 'app_read', return_value=False):
            run, deliver = self.run_speaker({'output': 'app-both', 'default_lang': 'en'})
        self.assertEqual(run.call_count, 2)      # the Mac's own voice instead
        deliver.assert_called_once()

    def test_app_both_when_the_app_did_not_speak(self):
        for stage in ('not-clicked', 'no-sound'):
            with mock.patch.object(speak, 'app_phone', return_value=stage):
                run, deliver = self.run_speaker({'output': 'app-both', 'default_lang': 'en'})
            self.assertEqual(run.call_count, 2)  # the Mac's voices
            deliver.assert_called_once()         # and the text to the phone

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
# A stand-in for app-voice-tap --stdout: records its arguments, then acts out $MODE, with the
# audio ($DIR/audio) on standard output and its status lines on standard error.
printf '%s\n' "$@" > "$DIR/args"
case "$MODE" in
  ok)       echo ready >&2; cat "$DIR/audio"; echo "streamed 1.0 s to standard output; the app went quiet" >&2; exit 0 ;;
  refused)  echo "System Audio Recording is off for app-voice-tap" >&2; exit 3 ;;
  silent)   echo ready >&2; echo "no sound from the Claude app within 10.0 s" >&2; exit 6 ;;
  hang)     echo ready >&2; exec sleep 30 ;;
  endless)  echo ready >&2; while cat "$DIR/audio"; do :; done; exit 0 ;;
  mute)     exec sleep 30 ;;
esac
'''

AUDIO = bytes(range(256)) * 188          # 48,128 bytes: about a second at 24 kHz


def drain(sock, into):
    """Reads `sock` to its end into the bytearray `into` (in a thread), then closes it."""
    def run():
        with sock:
            while chunk := sock.recv(65536):
                into.extend(chunk)
    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread


class FakeToolCase(Isolated):
    """A shell script standing in for app-voice-tap (no audio is captured)."""

    def setUp(self):
        super().setUp()
        self.tool = os.path.join(self.dir.name, 'app-voice-tap')
        with open(self.tool, 'w') as f:
            f.write(FAKE_TAP)
        os.chmod(self.tool, 0o755)
        with open(os.path.join(self.dir.name, 'audio'), 'wb') as f:
            f.write(AUDIO)

    def mode(self, mode):
        """The environment in which the tool (started meanwhile) acts out `mode`."""
        return mock.patch.dict(os.environ, {'MODE': mode, 'DIR': self.dir.name})

    def tap(self, mode):
        with self.mode(mode):
            tap = speak.Tap(self.tool)
        self.addCleanup(lambda: tap.proc.poll() is None and tap.proc.kill())
        return tap

    def read(self, name):
        with open(os.path.join(self.dir.name, name), encoding='utf-8') as f:
            return f.read()


class TapTests(FakeToolCase):
    """The Tap wrapper, relaying into a local socket pair."""

    def pair(self):
        a, b = socket.socketpair()
        self.addCleanup(a.close)
        self.addCleanup(b.close)
        return a, b

    def test_a_reading_is_relayed_whole(self):
        tap = self.tap('ok')
        self.assertTrue(tap.wait_ready())
        self.assertEqual(self.read('args').split('\n')[:-1],
                         ['--stdout', '--mute', '--rate', str(speak.STREAM_RATE), '--wait-start',
                          str(speak.TAP_WAIT_START), '--max-seconds', str(speak.TAP_MAX_SECONDS)])
        mine, phone = self.pair()
        received = bytearray()
        reader = drain(phone, received)
        self.assertIsNone(tap.relay(mine, timeout=10))
        self.assertEqual(tap.stop(), 0)
        self.assertEqual(tap.last_line(), 'streamed 1.0 s to standard output; the app went quiet')
        speak.end_stream(mine)
        reader.join(5)
        self.assertEqual(bytes(received), AUDIO)
        self.assertAlmostEqual(tap.seconds, len(AUDIO) / 48000)

    def test_refused_before_ready(self):
        tap = self.tap('refused')
        self.assertFalse(tap.wait_ready(timeout=5))
        self.assertEqual(tap.stop(grace=0), 3)
        self.assertEqual(tap.last_line(), 'System Audio Recording is off for app-voice-tap')

    def test_no_sound(self):
        tap = self.tap('silent')
        self.assertTrue(tap.wait_ready())
        self.assertIsNone(tap.relay(self.pair()[0], timeout=5))
        self.assertEqual(tap.stop(), speak.TAP_NO_SOUND)
        self.assertEqual(tap.last_line(), 'no sound from the Claude app within 10.0 s')
        self.assertEqual(tap.sent, 0)

    def test_never_ready_is_stopped(self):
        tap = self.tap('mute')
        self.assertFalse(tap.wait_ready(timeout=0.3))
        self.assertLess(tap.stop(grace=0), 0)          # terminated
        self.assertEqual(tap.last_line(), 'no output')

    def test_a_relay_that_runs_too_long_is_cut_short(self):
        tap = self.tap('hang')
        self.assertTrue(tap.wait_ready())
        self.assertEqual(tap.relay(self.pair()[0], timeout=0.3), 'still going after 0 s')
        self.assertLess(tap.stop(grace=0), 0)

    def test_babble_past_its_limit_is_cut(self):
        tap = self.tap('endless')
        self.assertTrue(tap.wait_ready())
        mine, phone = self.pair()
        received = bytearray()
        drain(phone, received)
        cut = tap.relay(mine, timeout=10, limit=0.5)
        self.assertTrue(cut.startswith('babble cut at '), cut)
        self.assertGreater(tap.seconds, 0.5)
        self.assertLess(tap.stop(grace=0), 0)

    def test_the_phone_closing_cuts_it_short(self):
        tap = self.tap('hang')
        self.assertTrue(tap.wait_ready())
        mine, phone = self.pair()
        phone.close()                                   # a newer message, or Stop
        self.assertEqual(tap.relay(mine, timeout=5), 'the phone ended the stream (a newer message or Stop)')
        self.assertLess(tap.stop(grace=0), 0)

    def test_a_phone_that_takes_nothing_is_given_up_on(self):
        tap = self.tap('endless')
        self.assertTrue(tap.wait_ready())
        mine, _ = self.pair()                           # nobody reads the other end
        mine.settimeout(0.2)
        self.assertTrue(tap.relay(mine, timeout=10).startswith('the phone took no audio'))
        self.assertLess(tap.stop(grace=0), 0)

    def test_the_tool_ends_when_nobody_reads_its_audio(self):
        # What happens when the speaker dies: the pipe closes, writing fails, and the tool exits.
        tap = self.tap('endless')
        self.assertTrue(tap.wait_ready())
        tap.proc.stdout.close()
        tap.proc.wait(5)
        tap.proc.stderr.close()
        self.assertIsNotNone(tap.proc.returncode)


class StreamHeaderTests(unittest.TestCase):
    def test_token_first_text_last(self):
        self.assertEqual(speak.stream_header('123456', 'Hello.'),
                         b'{"token":"123456","channels":1,"format":"pcm16","kind":"stream","rate":24000,"text":"Hello."}\n')
        long = speak.stream_header('123456', 'x' * 5000)
        self.assertIn(b'"token":"123456"', long[:64])     # the code in the first bytes, however long the text

    def test_no_text_and_utf8(self):
        self.assertEqual(json.loads(speak.stream_header('123456')),
                         {'channels': 1, 'format': 'pcm16', 'kind': 'stream', 'rate': 24000, 'token': '123456'})
        self.assertIn('囲碁'.encode(), speak.stream_header('123456', '囲碁'))
        self.assertEqual(speak.stream_header('1', 'a\nb').count(b'\n'), 1)     # one line, whatever the text


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


class BabbleLimitTests(unittest.TestCase):
    def test_short_text_gets_the_margin_long_text_the_factor(self):
        short = 'Sell the sizzle, not the steak.'
        expected = speak.reading_seconds(short) - speak.READ_LEAD
        self.assertAlmostEqual(speak.babble_limit(short), expected + speak.BABBLE_MARGIN)
        self.assertLess(speak.babble_limit(short), 25.7)               # 2026-10-14 19:12: cut
        long = ' '.join(['word'] * 250)                                 # about 90 s
        expected = speak.reading_seconds(long) - speak.READ_LEAD
        self.assertAlmostEqual(speak.babble_limit(long), expected * speak.BABBLE_FACTOR)

    def test_settings_and_off(self):
        self.assertAlmostEqual(speak.babble_limit('Hi.', {'babble_factor': 3, 'babble_margin': 1}),
                               max((speak.reading_seconds('Hi.') - speak.READ_LEAD) * 3,
                                   speak.reading_seconds('Hi.') - speak.READ_LEAD + 1))
        self.assertIsNone(speak.babble_limit('Hi.', {'babble_margin': 0}))
        self.assertIsNotNone(speak.babble_limit('Hi.', {'babble_factor': 'x'}))


class FakeTap:
    """Stands in for speak.Tap (calling it "starts" it): `ready`, then `relay`'s answer `cut`,
    the exit `status`, and its `line`."""

    def __init__(self, ready=True, cut=None, status=0, line='streamed 3.2 s to standard output; the app went quiet'):
        self.ready, self.cut, self.status, self.line = ready, cut, status, line
        self.stopped = self.relayed = None
        self.seconds = 3.2

    def __call__(self, path, mute=True):
        self.path, self.mute = path, mute
        return self

    def wait_ready(self):
        return self.ready

    def relay(self, sock, timeout, record=None, copy=None, limit=None):
        self.record = record
        self.limit = limit
        self.relayed = sock
        return self.cut

    def stop(self, grace=3.0):
        self.stopped = grace
        return self.status

    def last_line(self):
        return self.line


class AppPhoneTests(Isolated):
    """output app-phone's choices, with the tool, the click, and the phone mocked."""

    CFG = dict(speak.DEFAULTS, output='app-phone', phone_token='123456', phone='old.local:47811')

    def run_app_phone(self, tap=None, clicked=True, opened='ok', path='/bin/app-voice-tap', cfg=None):
        cfg = cfg or dict(self.CFG)
        self.write_config(cfg)
        tap = tap or FakeTap()
        self.sock = mock.Mock()
        if opened == 'ok':
            opened = (self.sock, {'ok': True, 'app': 'Sakamoto Voice', 'version': '0.3.0'})
        elif isinstance(opened, dict) or opened == 'silent':
            opened = (self.sock, None if opened == 'silent' else opened)
        with mock.patch.object(speak, 'tap_path', return_value=path), \
             mock.patch.object(speak, 'Tap', tap), \
             mock.patch.object(speak, 'reach_phone', return_value=opened) as reach, \
             mock.patch.object(speak, 'open_stream') as open_stream, \
             mock.patch.object(speak, 'end_stream') as end_stream, \
             mock.patch.object(speak, 'app_read', return_value=clicked) as click, \
             mock.patch.object(speak, 'deliver_to_phone') as deliver:
            speak.app_phone(cfg, 'Hello 囲碁', 'Hello 囲碁', [('default', 'Hello'), ('ja', '囲碁')], [('en', 'Hello')], set())
            if reach.called:
                reach.call_args[0][0]('Example-iPhone.local:47811')      # what it tries at an address
                self.opened_with = open_stream.call_args[0]
        self.end_stream = end_stream
        return tap, reach, click, deliver

    def test_both_streams_unmuted_and_reports_failures_instead_of_falling_back(self):
        with mock.patch.object(speak, 'tap_path', return_value='/bin/app-voice-tap'), \
             mock.patch.object(speak, 'Tap', FakeTap()) as tap, \
             mock.patch.object(speak, 'reach_phone', return_value=(mock.Mock(), {'ok': True})), \
             mock.patch.object(speak, 'open_stream'), mock.patch.object(speak, 'end_stream'), \
             mock.patch.object(speak, 'app_read', return_value=False), \
             mock.patch.object(speak, 'deliver_to_phone') as deliver:
            self.write_config(self.CFG)
            stage = speak.app_phone(self.CFG, 'Hi', 'Hi', [('default', 'Hi')], [('en', 'Hi')], set(), both=True)
        self.assertEqual((stage, tap.mute), ('not-clicked', False))
        deliver.assert_not_called()

    def assert_text_fallback(self, deliver):
        cfg, text, runs, _, _ = deliver.call_args[0]
        self.assertEqual((cfg['phone_mode'], text, runs), ('text', 'Hello 囲碁', [('default', 'Hello'), ('ja', '囲碁')]))

    def test_the_apps_voice_is_streamed(self):
        tap, reach, click, deliver = self.run_app_phone()
        self.assertEqual(self.opened_with, ('Example-iPhone.local:47811', speak.stream_header('123456', 'Hello 囲碁')))
        self.assertEqual(tap.path, '/bin/app-voice-tap')
        self.assertIs(tap.relayed, self.sock)
        self.assertLessEqual(click.call_args.kwargs['delay'], speak.APP_READ_DELAY)   # less the time spent
        self.end_stream.assert_called_once_with(self.sock)
        deliver.assert_not_called()
        self.assertIn('app-phone: 3.2 s to the phone; app-voice-tap: streamed 3.2 s', self.log_text())

    def test_debugger_off_sends_the_text(self):
        tap, _, _, deliver = self.run_app_phone(clicked=False)
        self.assertEqual(tap.stopped, 0)
        self.assertIsNone(tap.relayed)
        self.sock.close.assert_called()
        self.assert_text_fallback(deliver)
        self.assertIn("debugger is off", self.log_text())

    def test_a_tap_that_does_not_start_sends_the_text(self):
        tap, _, click, deliver = self.run_app_phone(FakeTap(ready=False, status=3, line='System Audio Recording is off'))
        click.assert_not_called()
        self.assertEqual(tap.stopped, 0)
        self.sock.close.assert_called()
        self.assert_text_fallback(deliver)
        self.assertIn('did not start: System Audio Recording is off', self.log_text())

    def test_a_tool_that_cannot_run_sends_the_text(self):
        def broken(path, mute=True):
            raise PermissionError('not executable')
        _, _, click, deliver = self.run_app_phone(broken)
        click.assert_not_called()
        self.sock.close.assert_called()
        self.assert_text_fallback(deliver)
        self.assertIn('did not start: not executable', self.log_text())

    def test_no_sound_sends_the_text(self):
        _, _, _, deliver = self.run_app_phone(FakeTap(status=speak.TAP_NO_SOUND, line='no sound'))
        self.sock.close.assert_called()
        self.end_stream.assert_not_called()
        self.assert_text_fallback(deliver)
        self.assertIn('no sound from the Claude app (no sound)', self.log_text())

    def test_not_built_sends_the_text(self):
        _, reach, click, deliver = self.run_app_phone(path=None)
        reach.assert_not_called()
        click.assert_not_called()
        self.assert_text_fallback(deliver)
        self.assertIn('mac/build.sh', self.log_text())

    def test_no_phone_reads_nothing_aloud(self):
        tap, _, click, deliver = self.run_app_phone(opened=None)
        click.assert_not_called()
        deliver.assert_not_called()
        self.assertFalse(hasattr(tap, 'path'))
        self.assertIn('the phone did not answer (unreachable)', self.log_text())

    def test_a_refused_stream_reads_nothing_aloud(self):
        tap, _, click, deliver = self.run_app_phone(opened={'ok': False, 'error': 'bad token'})
        click.assert_not_called()
        deliver.assert_not_called()
        self.assertFalse(hasattr(tap, 'path'))
        self.sock.close.assert_called()
        self.assertIn('refused the stream (bad token)', self.log_text())

    def test_an_old_phone_gets_the_text(self):
        tap, _, click, deliver = self.run_app_phone(opened='silent')
        click.assert_not_called()
        self.assertFalse(hasattr(tap, 'path'))
        self.sock.close.assert_called()
        self.assert_text_fallback(deliver)
        self.assertIn('is its app 0.3.0 or later?', self.log_text())

    def test_the_phone_ending_it_is_only_logged(self):
        tap, _, _, deliver = self.run_app_phone(FakeTap(cut='the phone ended the stream (a newer message or Stop)'))
        self.assertEqual(tap.stopped, 0)
        self.end_stream.assert_not_called()
        self.sock.close.assert_called()
        deliver.assert_not_called()
        self.assertIn('app-phone: the phone ended the stream (a newer message or Stop), after 3.2 s', self.log_text())

    def test_a_tool_failure_mid_stream_is_only_logged(self):
        _, _, _, deliver = self.run_app_phone(FakeTap(status=5, line="couldn't tap the Claude app"))
        deliver.assert_not_called()
        self.assertIn("status 5: couldn't tap the Claude app", self.log_text())

    def test_unpaired(self):
        _, reach, click, deliver = self.run_app_phone(cfg=dict(self.CFG, phone_token=''))
        reach.assert_not_called()
        click.assert_not_called()
        deliver.assert_not_called()
        self.assertIn('not paired', self.log_text())


class StreamPhone:
    """A stand-in phone for streams on the loopback interface: for each connection it reads the
    header line, answers it with `reply` (or, as phones before 0.3.0, not at all), then keeps the
    audio until the sender closes, and closes."""

    def __init__(self, reply):
        self.reply = reply
        self.headers, self.audio = [], []
        self.done = threading.Event()
        self.sock = socket.socket()
        try:
            self.sock.bind(('127.0.0.1', 0))
            self.sock.listen()
        except OSError:
            self.sock.close()
            raise
        self.address = f'127.0.0.1:{self.sock.getsockname()[1]}'
        threading.Thread(target=self.serve, daemon=True).start()

    def serve(self):
        while True:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            with conn:
                data = b''
                while b'\n' not in data and (chunk := conn.recv(4096)):
                    data += chunk
                header, _, audio = data.partition(b'\n')
                self.headers.append(json.loads(header))
                if self.reply is None:
                    conn.recv(1)                 # waits for the sender to give up
                    continue
                conn.sendall(json.dumps(self.reply).encode() + b'\n')
                if not self.reply.get('ok'):
                    continue
                while chunk := conn.recv(65536):
                    audio += chunk
                self.audio.append(audio)
                self.done.set()

    def close(self):
        self.sock.close()


class StreamTests(FakeToolCase):
    """app-phone over the loopback interface: speak.py's side of the stream, with the fake tool."""

    def phone(self, reply={'ok': True, 'app': 'Sakamoto Voice', 'version': 'test'}):
        try:
            phone = StreamPhone(reply)
        except OSError as e:
            self.skipTest(f'cannot listen here: {e}')
        self.addCleanup(phone.close)
        return phone

    def test_open_stream(self):
        phone = self.phone()
        sock, ack = speak.open_stream(phone.address, speak.stream_header('123456', 'Hi'))
        speak.end_stream(sock)
        self.assertTrue(ack['ok'])
        self.assertEqual(phone.headers, [{'channels': 1, 'format': 'pcm16', 'kind': 'stream', 'rate': 24000,
                                          'text': 'Hi', 'token': '123456'}])

    def test_a_refusal(self):
        phone = self.phone({'ok': False, 'error': 'bad token'})
        sock, ack = speak.open_stream(phone.address, speak.stream_header('111111'))
        sock.close()
        self.assertEqual(ack['error'], 'bad token')

    def test_an_old_phone_does_not_answer(self):
        phone = self.phone(None)
        sock, ack = speak.open_stream(phone.address, speak.stream_header('123456'), timeout=0.3)
        sock.close()
        self.assertIsNone(ack)

    def test_nobody_listening(self):
        self.phone()                                    # skipped where it can't listen
        with self.assertRaises(OSError):
            speak.open_stream(closed_port(), speak.stream_header('123456'))

    def run_app_phone(self, mode, phone, remembered=None):
        cfg = dict(speak.DEFAULTS, output='app-phone', phone_token='123456', phone=remembered or phone.address)
        self.write_config(cfg)
        with self.mode(mode), \
             mock.patch.object(speak, 'tap_path', return_value=self.tool), \
             mock.patch.object(speak, 'find_phone', return_value=('iPhone', phone.address)) as find, \
             mock.patch.object(speak, 'app_read', return_value=True), \
             mock.patch.object(speak, 'deliver_to_phone') as deliver:
            speak.app_phone(cfg, 'Hello', 'Hello', [('default', 'Hello')], [('en', 'Hello')], set())
        return find, deliver

    def test_the_tools_audio_reaches_the_phone(self):
        phone = self.phone()
        find, deliver = self.run_app_phone('ok', phone)
        self.assertTrue(phone.done.wait(5))
        self.assertEqual(phone.headers[0]['text'], 'Hello')
        self.assertEqual(phone.audio, [AUDIO])
        find.assert_not_called()
        deliver.assert_not_called()
        self.assertIn('app-phone: 1.0 s to the phone; app-voice-tap: streamed 1.0 s', self.log_text())

    def test_a_phone_that_moved_is_found_again(self):
        phone = self.phone()
        find, _ = self.run_app_phone('ok', phone, remembered=closed_port())
        self.assertTrue(phone.done.wait(5))
        find.assert_called_once_with('123456')
        self.assertEqual(self.read_config()['phone'], phone.address)
        self.assertEqual(phone.audio, [AUDIO])

    def test_no_sound_closes_the_stream_and_sends_the_text(self):
        phone = self.phone()
        _, deliver = self.run_app_phone('silent', phone)
        self.assertTrue(phone.done.wait(5))
        self.assertEqual(phone.audio, [b''])
        deliver.assert_called_once()

    def test_the_mac_app_is_streamed_to_like_a_phone_and_the_mac_stays_quiet(self):
        # Sakamoto Eyes' Mac app (2026-10-17): her voice's receiver on 127.0.0.1, which the hub
        # names in the route as a phone's. app-both plays as app-phone there: the Claude app's
        # voice is tapped muted (the Mac's speakers quiet) and streamed to the Mac app, which
        # plays it through its own echo canceller; nothing else is tried.
        mac_app = self.phone()
        path = os.path.join(self.dir.name, 'voice-route.json')
        with open(path, 'w') as f:
            json.dump({'room': 'Lab', 'phone': 'Mac', 'addresses': [mac_app.address], 'fallback': 'any',
                       'at_unix': time.time() - 5, 'phones': [{'name': 'Mac', 'room': 'Lab',
                                                               'addresses': [mac_app.address]}]}, f)
        self.write_config(dict(speak.DEFAULTS, output='app-both', phone_token='123456', phone=closed_port(),
                               phone_route=path, default_lang='en'))
        fd, text = tempfile.mkstemp(dir=self.dir.name)
        with os.fdopen(fd, 'w') as f:
            f.write('Hello')
        mutes = []
        real = speak.Tap

        def tap(path, mute=True):
            mutes.append(mute)
            return real(path, mute=mute)
        with self.mode('ok'), \
             mock.patch.object(speak, 'tap_path', return_value=self.tool), \
             mock.patch.object(speak, 'Tap', tap), \
             mock.patch.object(speak, 'find_phone') as find, \
             mock.patch.object(speak, 'app_read', return_value=True), \
             mock.patch.object(speak, 'app_read_here') as here, \
             mock.patch.object(speak, 'mac_says') as says, \
             mock.patch.object(speak, 'deliver_to_phone') as deliver:
            speak.speak(text, turn='heard')
        self.assertTrue(mac_app.done.wait(5))
        self.assertEqual(mac_app.audio, [AUDIO])
        self.assertEqual(mutes, [True])
        for unused in (find, here, says, deliver):
            unused.assert_not_called()
        self.assertIn('voice route (heard): Mac', self.log_text())


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



class NothingToSay(unittest.TestCase):
    def test_an_ellipsis_or_an_emoji_is_nothing_to_say(self):
        for text in ('08:31 …', '8:31…', '…', '07:24 ...', ' 08:31 … ', '08:31 🦉', '08:31 🏓🎉',
                     '08:31 👩🏻‍🔬', '🫖', '08:31 🎉 🤔', '08:31 🧜🏻‍♀️🕵🏻‍♀️🇯🇵',
                     # Sakamoto Eyes' avatar escapes: become a mermaid, come back, think of herself.
                     '09:06 👩🏻‍🔬🧜🏻‍♀️', '09:06 👩🏻‍🔬🧜🏻‍♀️🎉🤔', '09:06 👩🏻‍🔬👩🏻‍🔬', '09:06 👩🏻‍🔬👩🏻‍🔬👩🏻‍🔬',
                     # 2026-10-17, the skeptic: her time after the emoji, its own last line or not.
                     '👍\n13:40', '😊 13:40', '👍\n\n13:40\n', '…\n13:40'):
            self.assertTrue(speak.nothing_to_say(text), text)

    def test_her_time_sign_off_alone_is_nothing_to_say(self):
        # John, 2026-10-17 15:35: it makes no sound, in any mode. Her sign-off is the minute she
        # replied in (or up to two before); any other bare time is an answer, and is spoken.
        now = time.mktime((2026, 10, 17, 13, 40, 20, 0, 0, -1))
        for text in ('13:40', ' 13:40\n', '13:39 ', '13:38'):
            self.assertTrue(speak.nothing_to_say(text, now), text)
        for text in ('8:30', '13:37', '13:41', '08:31'):
            self.assertFalse(speak.nothing_to_say(text, now), text)
        self.assertTrue(speak.nothing_to_say(time.strftime('%H:%M')))     # this minute, by default

    def test_anything_more_is_spoken(self):
        for text in ('08:31 … hello', '08:31 Bumble', 'Wait…', '08:31 🦉 owl', '08:31 ★☆★☆', '08:31:15',
                     '08:31 🎉🤔👍🦉', '09:06 👩🏻‍🔬🧜🏻‍♀️🎉🤔👍', 'Yes.\n13:40', '8 minutes', 'Yes. 13:40',
                     '👍 Done.\n13:40'):
            self.assertFalse(speak.nothing_to_say(text), text)

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


class PromptedAndRemote(SpeakerTests):
    """A response after a notice still tries the app's voice (app-read guards against a shared
    block); phone_remote is tried first."""

    def test_unprompted_app_output_still_tries_the_app(self):
        with mock.patch.object(speak, 'app_read', return_value=True) as click:
            self.run_speaker({'output': 'app', 'default_lang': 'en'}, prompted=False)
        click.assert_called_once()

    def test_prompted_marks(self):
        self.assertTrue(os.path.basename(speak.PROMPTED) and os.path.basename(speak.RESPONDED))

    def test_remote_first(self):
        self.write_config({'phone_token': '123456', 'phone': 'Example-iPhone.local:47811',
                           'phone_remote': '100.64.0.9:47811'})
        tried = []
        def attempt(address):
            tried.append(address)
            return 'ok'
        self.assertEqual(speak.reach_phone(attempt), 'ok')
        self.assertEqual(tried, ['100.64.0.9:47811'])

    def test_remote_failing_falls_back_to_the_local_network(self):
        self.write_config({'phone_token': '123456', 'phone': 'Example-iPhone.local:47811',
                           'phone_remote': '100.64.0.9:47811'})
        tried = []
        def attempt(address):
            tried.append(address)
            if address.startswith('100.'):
                raise OSError('unreachable')
            return 'ok'
        self.assertEqual(speak.reach_phone(attempt), 'ok')
        self.assertEqual(tried, ['100.64.0.9:47811', 'Example-iPhone.local:47811'])


class VoiceRoute(SpeakerTests):
    """Sakamoto Eyes' voice route (phone_route): a reply to a line it heard goes to the phone in
    the room where the conversation is, and only there, with the Mac quiet; what she says
    unprompted goes to every phone the hub lists; a reply to a typed prompt is as before."""

    LAB = {'name': 'Lab XS', 'room': 'Lab', 'addresses': ['192.168.1.40:47811'], 'fallback': 'stream_only'}
    DEN = {'name': '16 Pro', 'room': 'Den', 'addresses': ['192.168.1.50:47811', '100.64.0.50:47811'],
           'fallback': 'any'}

    def write_route(self, addresses, age=10, fallback='stream_only', phones=None):
        path = os.path.join(self.dir.name, 'voice-route.json')
        route = {'room': 'Lab', 'phone': 'Lab XS', 'addresses': addresses, 'fallback': fallback,
                 'at_unix': speak.time.time() - age}
        if phones is not None:
            route['phones'] = phones
        with open(path, 'w') as f:
            json.dump(route, f)
        return path

    def test_a_reply_to_a_heard_line_goes_only_to_the_routed_phone(self):
        route = self.write_route(['192.168.1.40:47811', '100.64.0.40:47811'])
        self.write_config({'phone_token': '123456', 'phone': 'Example-iPhone.local:47811',
                           'phone_remote': '100.64.0.9:47811', 'phone_route': route})
        cfg = speak.routed(speak.config(), 'heard')
        self.assertEqual(cfg['targets'], [{'name': 'Lab XS', 'addresses': ['192.168.1.40:47811', '100.64.0.40:47811'],
                                           'fallback': 'stream_only'}])
        tried = []

        def attempt(address):
            tried.append(address)
            if address.startswith('192.'):
                raise OSError('unreachable')
            return 'ok'
        self.assertEqual(speak.reach_phone(attempt, cfg['targets'][0]), 'ok')
        self.assertEqual(tried, ['192.168.1.40:47811', '100.64.0.40:47811'])
        self.assertEqual(self.read_config()['phone'], 'Example-iPhone.local:47811')   # not saved

    def test_a_routed_phone_that_does_not_answer_means_silence(self):
        # Never the usual phone, which may be in another room.
        route = self.write_route(['192.168.1.40:47811'])
        self.write_config({'phone_token': '123456', 'phone': 'Example-iPhone.local:47811',
                           'phone_remote': '100.64.0.9:47811', 'phone_route': route})
        tried = []

        def attempt(address):
            tried.append(address)
            raise OSError('unreachable')
        with mock.patch.object(speak, 'find_phone') as find:
            self.assertIsNone(speak.reach_phone(attempt, speak.routed(speak.config(), 'heard')['targets'][0]))
        self.assertEqual(tried, ['192.168.1.40:47811'])
        find.assert_not_called()
        self.assertIn('Lab XS did not answer; silent there', self.log_text())

    def test_a_stale_or_empty_route_changes_nothing(self):
        for route in (self.write_route(['192.168.1.40:47811'], age=31 * 60), self.write_route([]),
                      os.path.join(self.dir.name, 'missing.json')):
            cfg = {'phone_token': '123456', 'phone_remote': '100.64.0.9:47811', 'phone_route': route,
                   'output': 'app-both'}
            self.assertEqual(speak.route_addresses(cfg), [])
            self.assertEqual(speak.routed(cfg, 'heard'), cfg)

    def write_mac_route(self, age=10, phones=None):
        """The hub's route to the Mac's speakers: the Mac app's room, no phone and no address."""
        path = os.path.join(self.dir.name, 'voice-route.json')
        with open(path, 'w') as f:
            json.dump({'room': 'Lab', 'addresses': [], 'mac': True, 'at_unix': speak.time.time() - age,
                       'phones': [self.DEN] if phones is None else phones}, f)
        return path

    def test_a_route_to_the_mac_plays_there_only(self):
        # John, 2026-10-17 07:49: he talked to her through the Mac app in the Lab, and with no
        # address in the route her voice went to the configured phone, the 16 Pro in Nerdvana.
        route = self.write_mac_route()
        for output, expected in (('app-phone', 'app'), ('app-both', 'app'), ('app', 'app'),
                                 ('phone', 'mac'), ('both', 'mac'), ('mac', 'mac'), ('radio', 'mac')):
            cfg = speak.routed({'phone_token': '123456', 'phone_route': route, 'output': output}, 'heard')
            self.assertEqual(cfg['output'], expected, output)
            self.assertNotIn('targets', cfg)
        self.assertEqual(speak.route_addresses({'phone_route': route}), [])
        self.assertTrue(speak.voice_route({'phone_route': route})['mac'])

    def test_on_the_mac_the_phones_get_nothing(self):
        route = self.write_mac_route()
        run, deliver = self.run_speaker({'output': 'both', 'default_lang': 'en', 'phone_token': '123456',
                                         'phone': 'Example-iPhone.local:47811', 'phone_route': route}, turn='heard')
        self.assertEqual(self.spoken(run), ['Hello', '囲碁'])
        deliver.assert_not_called()
        self.assertIn('voice route (heard): the Mac (mac)', self.log_text())
        with mock.patch.object(speak, 'app_phone') as app_phone, \
             mock.patch.object(speak, 'app_read_here', return_value=lambda: None) as here:
            run, deliver = self.run_speaker({'output': 'app-phone', 'default_lang': 'en', 'phone_token': '123456',
                                             'phone_route': route}, turn='heard')
        here.assert_called_once()
        app_phone.assert_not_called()
        deliver.assert_not_called()
        run.assert_not_called()

    def test_a_stale_route_to_the_mac_changes_nothing(self):
        route = self.write_mac_route(age=31 * 60)
        cfg = {'phone_token': '123456', 'phone_route': route, 'output': 'app-phone'}
        self.assertEqual(speak.routed(cfg, 'heard'), cfg)

    def test_typed_and_unprompted_replies_never_follow_a_route(self):
        # 2026-10-17 13:45-14:02: replies to typed prompts played on the Mac for Labmac, where a
        # route 5 minutes old pointed, while John sat in Nerdvana. A route says where a heard line
        # came from, not where anyone is now; with the hub's levels, see VoiceRules.
        for age in (60, 4 * 60, 20 * 60):
            route = self.write_mac_route(age=age)
            cfg = {'phone_token': '123456', 'phone_route': route, 'output': 'app-both'}
            self.assertEqual(speak.routed(cfg, 'typed'), cfg, age)
            self.assertEqual([t['name'] for t in speak.routed(cfg, 'notice')['targets']], ['16 Pro'], age)
            self.assertFalse(hasattr(speak, 'FOLLOW_MAX_AGE'))
        path = os.path.join(self.dir.name, 'voice-route.json')
        with open(path, 'w') as f:
            json.dump({'room': 'Lab', 'phone': 'Mac', 'addresses': ['127.0.0.1:47823'], 'fallback': 'any',
                       'at_unix': speak.time.time() - 60, 'phones': [self.DEN]}, f)
        cfg = {'phone_token': '123456', 'phone_route': path, 'output': 'app-both'}
        self.assertEqual(speak.routed(cfg, 'typed'), cfg)
        # A heard line's reply keeps its route for 30 minutes.
        route = self.write_mac_route(age=20 * 60)
        self.assertTrue(speak.routed({'phone_route': route, 'output': 'app-both'}, 'heard').get('on_mac'))

    def test_a_malformed_route_never_raises(self):
        now = speak.time.time()
        path = os.path.join(self.dir.name, 'voice-route.json')
        shapes = [
            {'room': 'Lab', 'addresses': 5, 'at_unix': now},
            {'room': 'Lab', 'addresses': '127.0.0.1:47823', 'at_unix': now},
            {'room': 'Lab', 'addresses': [1, None, ['x'], '', '127.0.0.1:47823'], 'at_unix': now},
            {'room': 'Lab', 'addresses': {'a': 1}, 'mac': 'yes', 'at_unix': now},
            {'room': ['Lab'], 'phone': 7, 'fallback': 3, 'addresses': ['10.0.0.2:47811'], 'at_unix': now},
            {'addresses': ['10.0.0.2:47811'], 'at_unix': [now]},
            {'addresses': ['10.0.0.2:47811'], 'at_unix': 'soon'},
            {'addresses': ['10.0.0.2:47811'], 'at_unix': now, 'phones': {'a': 1}},
            {'addresses': [], 'at_unix': now,
             'phones': [3, 'x', {'addresses': 'x'}, {'name': 5, 'fallback': [], 'addresses': [5, '10.0.0.3:1']}]},
            ['not', 'a', 'dict'],
            'a string',
            None,
        ]
        for shape in shapes:
            with open(path, 'w') as f:
                json.dump(shape, f)
            cfg = {'phone_token': '123456', 'phone_route': path, 'output': 'app-both'}
            for turn in ('heard', 'typed', 'notice'):
                routed = speak.routed(cfg, turn)
                for target in routed.get('targets') or []:
                    self.assertTrue(all(isinstance(a, str) and a for a in target['addresses']), (shape, turn))
                    self.assertIsInstance(target['name'], str)
                    self.assertIsInstance(target['fallback'], str)
                ', '.join(map(speak.target_name, routed.get('targets') or []))   # the speaker's log line
        with open(path, 'w') as f:
            json.dump(shapes[2], f)
        self.assertEqual(speak.route_addresses({'phone_route': path}), ['127.0.0.1:47823'])
        with open(path, 'w') as f:
            json.dump(shapes[1], f)
        self.assertEqual(speak.route_addresses({'phone_route': path}), [])

    def test_a_mac_app_that_does_not_answer_falls_back_to_the_macs_speakers(self):
        # The Mac app is in the Mac's own room: when its receiver refuses, the Claude app reads on
        # the Mac, not silence (a phone elsewhere that doesn't answer still means silence).
        path = os.path.join(self.dir.name, 'voice-route.json')
        with open(path, 'w') as f:
            json.dump({'room': 'Lab', 'phone': 'Mac', 'addresses': [closed_port()], 'fallback': 'any',
                       'at_unix': speak.time.time() - 5}, f)
        with mock.patch.object(speak, 'tap_path', return_value='/bin/app-voice-tap'), \
             mock.patch.object(speak, 'app_read', return_value=True) as click, \
             mock.patch.object(speak, 'app_read_here', return_value=lambda: None) as here:
            run, deliver = self.run_speaker({'output': 'app-both', 'default_lang': 'en', 'phone_token': '123456',
                                             'phone_route': path}, turn='heard')
        here.assert_called_once()
        click.assert_not_called()
        deliver.assert_not_called()
        run.assert_not_called()
        self.assertIn("the Mac app didn't answer; the Mac's own speakers", self.log_text())

    def test_a_reply_to_a_notice_goes_to_every_listed_phone_whatever_the_route(self):
        route = self.write_route(['192.168.1.40:47811'], phones=[self.LAB, self.DEN])
        run, deliver = self.run_speaker({'output': 'both', 'default_lang': 'en', 'phone_token': '123456',
                                         'phone_route': route}, prompted=False)
        self.assertEqual(self.spoken(run), ['Hello', '囲碁'])
        self.assertEqual([t['name'] for t in deliver.call_args[0][0]['targets']], ['Lab XS', '16 Pro'])
        self.assertIn('voice route (notice): Lab XS, 16 Pro', self.log_text())

    def test_a_reply_to_a_typed_prompt_is_as_before_without_a_fresh_route(self):
        for route in (self.write_route(['192.168.1.40:47811'], age=31 * 60, phones=[self.LAB, self.DEN]),
                      self.write_route([], phones=[self.LAB, self.DEN])):
            cfg = {'phone_token': '123456', 'phone_route': route, 'output': 'app-both'}
            self.assertEqual(speak.routed(cfg, 'typed'), cfg)

    def test_the_mac_stays_quiet_under_a_route(self):
        route = self.write_route(['192.168.1.40:47811'])
        for output, expected in (('both', 'phone'), ('app-both', 'app-phone'), ('mac', 'mac'), ('phone', 'phone')):
            self.assertEqual(speak.routed({'phone_route': route, 'output': output}, 'heard')['output'], expected)

    def test_under_a_route_the_mac_says_nothing(self):
        route = self.write_route(['192.168.1.40:47811'])
        run, deliver = self.run_speaker({'output': 'both', 'default_lang': 'en', 'phone_token': '123456',
                                         'phone_route': route}, turn='heard')
        self.assertEqual(self.spoken(run), [])
        deliver.assert_called_once()
        self.assertEqual(deliver.call_args[0][0]['targets'][0]['name'], 'Lab XS')

    def test_after_a_typed_prompt_the_mac_speaks_as_set(self):
        route = self.write_route(['192.168.1.40:47811'], age=31 * 60)
        run, deliver = self.run_speaker({'output': 'both', 'default_lang': 'en', 'phone_token': '123456',
                                         'phone_route': route}, turn='typed')
        self.assertEqual(self.spoken(run), ['Hello', '囲碁'])
        self.assertNotIn('targets', deliver.call_args[0][0])

    def test_unprompted_she_speaks_to_every_listed_phone_and_the_mac_as_set(self):
        # A reply to a notice is for everyone listening.
        route = self.write_route(['192.168.1.40:47811'], age=40 * 60, phones=[self.LAB, self.DEN, {'name': 'x'}])
        run, deliver = self.run_speaker({'output': 'both', 'default_lang': 'en', 'phone_token': '123456',
                                         'phone_route': route}, prompted=False)
        self.assertEqual(self.spoken(run), ['Hello', '囲碁'])
        self.assertEqual([t['name'] for t in deliver.call_args[0][0]['targets']], ['Lab XS', '16 Pro'])
        self.assertIn('voice route (notice): Lab XS, 16 Pro', self.log_text())

    def test_unprompted_without_listed_phones_is_as_before(self):
        route = self.write_route(['192.168.1.40:47811'], age=31 * 60, phones=[])
        cfg = {'phone_token': '123456', 'phone_route': route, 'output': 'app-phone'}
        self.assertEqual(speak.routed(cfg, 'notice'), cfg)

    def test_the_text_goes_to_each_target(self):
        route = self.write_route(['192.168.1.40:47811'], age=31 * 60, phones=[self.LAB, self.DEN])
        self.write_config({'phone_token': '123456', 'phone_route': route})
        cfg = speak.routed(speak.config(), 'notice')
        with mock.patch.object(speak, 'send_to_phone', return_value={'ok': True}) as send:
            speak.deliver_to_phone(cfg, 'Hello', [('default', 'Hello')], [('en', 'Hello')], set())
        self.assertEqual(sorted(c.kwargs['target']['name'] for c in send.call_args_list), ['16 Pro', 'Lab XS'])

    def test_a_failed_stream_to_the_phone_by_the_mac_falls_silent(self):
        route = self.write_route(['192.168.1.40:47811'], fallback='stream_only')
        cfg = speak.routed({'output': 'app-both', 'phone_token': '123456', 'phone_route': route}, 'heard')
        self.assertEqual(cfg['output'], 'app-phone')
        with mock.patch.object(speak, 'tap_path', return_value=''), \
             mock.patch.object(speak, 'deliver_to_phone') as deliver:
            self.assertIsNone(speak.app_phone(cfg, 'Hello', 'Hello', [], [('en', 'Hello')], set()))
        deliver.assert_not_called()
        self.assertIn('silent on Lab XS: it plays only the streamed voice', self.log_text())

    def test_a_failed_stream_to_a_phone_in_hand_falls_back_to_its_voices(self):
        for fallback in ('any', None):
            route = self.write_route(['192.168.1.40:47811'], fallback=fallback)
            cfg = speak.routed({'output': 'app-both', 'phone_token': '123456', 'phone_route': route}, 'heard')
            with mock.patch.object(speak, 'tap_path', return_value=''), \
                 mock.patch.object(speak, 'deliver_to_phone') as deliver:
                speak.app_phone(cfg, 'Hello', 'Hello', [], [('en', 'Hello')], set())
            deliver.assert_called_once()
            self.assertEqual(deliver.call_args[0][0]['targets'][0]['name'], 'Lab XS')

    def run_broadcast(self, answers):
        """app-phone to both listed phones (no fresh route), each answering its stream as `answers`
        says."""
        route = self.write_route(['192.168.1.40:47811'], age=31 * 60, phones=[self.LAB, self.DEN])
        self.write_config({'output': 'app-phone', 'phone_token': '123456', 'phone_route': route})
        cfg = speak.routed(speak.config(), 'notice')
        socks = {name: mock.Mock(name=name) for name in answers}
        tap = FakeTap()
        with mock.patch.object(speak, 'tap_path', return_value='/bin/app-voice-tap'), \
             mock.patch.object(speak, 'Tap', tap), \
             mock.patch.object(speak, 'reach_phone',
                               side_effect=lambda attempt, target: (socks[target['name']], answers[target['name']])), \
             mock.patch.object(speak, 'end_stream') as end_stream, \
             mock.patch.object(speak, 'app_read', return_value=True), \
             mock.patch.object(speak, 'deliver_to_phone') as deliver:
            speak.app_phone(cfg, 'Hello', 'Hello', [('default', 'Hello')], [('en', 'Hello')], set())
        return tap, socks, end_stream, deliver

    def test_unprompted_the_apps_voice_streams_to_every_phone(self):
        tap, socks, end_stream, deliver = self.run_broadcast({'Lab XS': {'ok': True}, '16 Pro': {'ok': True}})
        self.assertEqual(tap.relayed, [socks['Lab XS'], socks['16 Pro']])
        self.assertEqual(end_stream.call_count, 2)
        deliver.assert_not_called()
        self.assertIn('(2 of 2 phones)', self.log_text())

    def test_a_phone_that_wants_the_text_gets_it_while_the_other_streams(self):
        tap, socks, _, deliver = self.run_broadcast({'Lab XS': {'ok': True}, '16 Pro': dict(WANTS_TEXT)})
        self.assertIs(tap.relayed, socks['Lab XS'])
        socks['16 Pro'].close.assert_called()
        self.assertEqual([t['name'] for t in deliver.call_args[0][0]['targets']], ['16 Pro'])

    def test_stop_reaches_the_routed_phone_the_listed_ones_and_the_usual_one(self):
        route = self.write_route(['192.168.1.40:47811'], phones=[self.LAB, self.DEN])
        cfg = {'phone_token': '123456', 'phone_remote': '100.64.0.9:47811', 'phone_route': route,
               'output': 'app-both'}
        with mock.patch.object(speak, 'exchange') as exchange:
            speak.stop_phone(cfg)
        self.assertEqual([c.args[0] for c in exchange.call_args_list],
                         ['192.168.1.40:47811', '192.168.1.50:47811', '100.64.0.9:47811'])


class VoiceRules(SpeakerTests):
    """John's rules for her voice (2026-10-17 15:24), with Sakamoto Eyes' hub 0.2.35 levels in
    voice-route.json: (A) a reply goes to the room whose heard line asked for it; (B) a muted
    room (Mute or Ears off) hears her nowhere, not through another room or the Mac either; (C)
    its own screens show the reply instead (a silent_reply line for the hub); (D) a notice's or a
    typed prompt's reply goes to every device set to speak it, except in muted rooms."""

    LAB = {'name': 'Lab XS', 'room': 'Lab', 'addresses': ['192.168.1.40:47811'], 'fallback': 'stream_only'}
    NERDVANA = {'name': 'iPhone 16pro', 'room': 'Nerdvana', 'addresses': ['192.168.0.17:47811'], 'fallback': 'any'}
    MAC_APP = {'name': 'Mac', 'room': 'Labmac', 'addresses': ['127.0.0.1:47823'], 'fallback': 'any'}

    def write_hub(self, route=None, level='normal', levels=None, mac_silent=False, phones=None, age=10,
                  status_age=2, commands=True, mac_rooms=None, his_room=None):
        """The hub's state folder: voice-route.json (the route, if any, `age` seconds old; the
        levels; the phones, each marked silent when its room is), status.json written
        `status_age` seconds ago (None: none), and an empty commands.jsonl."""
        state = os.path.join(self.dir.name, 'eyes-ears')
        os.makedirs(state, exist_ok=True)
        levels = levels or {}
        silent = lambda room: levels.get(room, level) in ('mute', 'off')
        data = dict(route or {}, at_unix=speak.time.time() - age) if route else {}
        if mac_rooms is not None:
            data['mac_rooms'] = mac_rooms
        if his_room:
            data['his_room'] = his_room
        data.update({'level': level, 'levels': levels, 'mac_silent': mac_silent,
                     'silent_rooms': sorted(r for r in levels if silent(r)),
                     'phones': [dict(p, silent=True) if silent(p['room']) else p for p in (phones or [])]})
        path = os.path.join(state, 'voice-route.json')
        with open(path, 'w') as f:
            json.dump(data, f)
        status = os.path.join(state, 'status.json')
        if status_age is not None:
            with open(status, 'w') as f:
                f.write('{}')
            then = speak.time.time() - status_age
            os.utime(status, (then, then))
        if commands:
            open(os.path.join(state, 'commands.jsonl'), 'w').close()
        return path

    def commands(self):
        try:
            with open(os.path.join(self.dir.name, 'eyes-ears', 'commands.jsonl')) as f:
                return [json.loads(line) for line in f if line.strip()]
        except FileNotFoundError:
            return None

    def cfg(self, route, output='app-both'):
        return {'phone_token': '123456', 'phone_route': route, 'output': output, 'default_lang': 'en'}

    # A and B: a heard line's reply.

    def test_a_reply_goes_to_the_room_that_asked(self):
        route = self.write_hub({'room': 'Nerdvana', 'phone': 'iPhone 16pro', 'addresses': ['192.168.0.17:47811'],
                                'fallback': 'any'}, levels={'Nerdvana': 'normal', 'Lab': 'mute'},
                               phones=[self.LAB, self.NERDVANA])
        routed = speak.routed(self.cfg(route), 'heard')
        self.assertEqual([t['name'] for t in routed['targets']], ['iPhone 16pro'])
        self.assertEqual(routed['output'], 'app-phone')     # the Mac quiet

    def test_quiet_is_not_muted(self):
        # At Quiet only lines naming her reach her, and she answers them aloud in their room.
        route = self.write_hub({'room': 'Nerdvana', 'phone': 'iPhone 16pro', 'addresses': ['192.168.0.17:47811']},
                               level='quiet', levels={'Nerdvana': 'quiet'}, phones=[self.NERDVANA])
        self.assertEqual([t['name'] for t in speak.routed(self.cfg(route), 'heard')['targets']], ['iPhone 16pro'])
        self.assertFalse(speak.routed(self.cfg(route), 'typed').get('silent'))

    def test_a_muted_room_hears_her_nowhere_and_shows_the_reply(self):
        for level in ('mute', 'off'):
            for route in ({'room': 'Nerdvana', 'phone': 'iPhone 16pro', 'addresses': ['192.168.0.17:47811']},
                          {'room': 'Labmac', 'addresses': [], 'mac': True},
                          {'room': 'Labmac', 'phone': 'Mac', 'addresses': ['127.0.0.1:47823']}):
                path = self.write_hub(route, levels={route['room']: level, 'Lab': 'normal'},
                                      phones=[self.LAB, self.NERDVANA, self.MAC_APP])
                with mock.patch.object(speak, 'app_phone') as app_phone, \
                     mock.patch.object(speak, 'app_read_here') as here:
                    run, deliver = self.run_speaker(self.cfg(path), text='13:47 Muted rooms get it on the sign.',
                                                    turn='heard')
                run.assert_not_called()
                deliver.assert_not_called()
                app_phone.assert_not_called()
                here.assert_not_called()
                self.assertEqual(self.commands(), [{'cmd': 'silent_reply', 'room': route['room'],
                                                    'text': '13:47 Muted rooms get it on the sign.'}], (level, route))
                self.assertIn(f"voice route (heard): {route['room']} is muted; silent everywhere; shown there",
                              self.log_text())
                self.assertFalse(os.path.exists(speak.PIDFILE))

    def test_without_a_fresh_route_the_heard_lines_room_decides(self):
        path = self.write_hub(None, levels={'Nerdvana': 'mute'}, phones=[self.NERDVANA])
        with open(speak.LAST_PROMPT, 'w') as f:
            json.dump({'heard': True, 'rooms': ['Nerdvana'], 'at_unix': speak.time.time()}, f)
        self.assertEqual(speak.routed(self.cfg(path), 'heard').get('silent_in'), 'Nerdvana')
        with open(speak.LAST_PROMPT, 'w') as f:
            json.dump({'heard': True, 'rooms': ['Lab'], 'at_unix': speak.time.time()}, f)
        # No device listed in the Lab; the Mac's rooms unknown, so the Mac counts as there.
        self.assertEqual(speak.routed(self.cfg(path), 'heard'), dict(self.cfg(path), output='app', on_mac=True))

    def test_a_hub_that_stopped_silences_nothing(self):
        # Its levels count only while its status.json is fresh.
        for status_age in (speak.LEVELS_MAX_AGE + 5, None):
            path = self.write_hub({'room': 'Nerdvana', 'phone': 'iPhone 16pro', 'addresses': ['192.168.0.17:47811']},
                                  level='mute', phones=[self.NERDVANA], status_age=status_age)
            self.assertIsNone(speak.hub_levels(self.cfg(path)))
            self.assertEqual([t['name'] for t in speak.routed(self.cfg(path), 'heard')['targets']], ['iPhone 16pro'])
        # An older hub writes no levels: as before.
        route = os.path.join(self.dir.name, 'eyes-ears', 'voice-route.json')
        with open(route, 'w') as f:
            json.dump({'room': 'Lab', 'addresses': ['192.168.1.40:47811'], 'at_unix': speak.time.time()}, f)
        self.assertIsNone(speak.hub_levels(self.cfg(route)))

    def test_the_silent_reply_needs_the_hubs_folder(self):
        # The skeptic's follow-up: commands.jsonl is created when missing (the hub reads it once it
        # exists); the hub's folder never is.
        path = self.write_hub({'room': 'Nerdvana', 'phone': 'iPhone 16pro', 'addresses': ['192.168.0.17:47811']},
                              level='mute', phones=[self.NERDVANA], commands=False)
        self.assertTrue(speak.show_silently(speak.config() | self.cfg(path), 'Nerdvana', 'Hello.'))
        self.assertEqual(self.commands(), [{'cmd': 'silent_reply', 'room': 'Nerdvana', 'text': 'Hello.'}])
        gone = os.path.join(self.dir.name, 'no-hub', 'voice-route.json')
        self.assertFalse(speak.show_silently(self.cfg(gone), 'Nerdvana', 'Hello.'))
        self.assertFalse(os.path.exists(os.path.dirname(gone)))
        self.assertIn('silent reply for Nerdvana:', self.log_text())

    # D: what no room asked for.

    def test_the_incident_typed_replies_under_everyones_mute(self):
        # 2026-10-17 13:45-14:02: everyone's Mute; the route from 13:40 named Labmac (the Mac
        # app); John in Nerdvana. His typed prompts' replies played on the Mac. Now: nowhere,
        # and nothing shown (he reads them in the Claude app, where he typed).
        path = self.write_hub({'room': 'Labmac', 'phone': 'Mac', 'addresses': ['127.0.0.1:47823'], 'fallback': 'any'},
                              level='mute', levels={'Labmac': 'mute', 'Nerdvana': 'mute'}, mac_silent=True,
                              phones=[self.MAC_APP, self.NERDVANA], age=2 * 60)
        for turn, prompted in (('typed', True), ('notice', False)):
            with mock.patch.object(speak, 'app_phone') as app_phone, \
                 mock.patch.object(speak, 'app_read_here') as here:
                run, deliver = self.run_speaker(self.cfg(path), prompted=prompted, turn=turn)
            run.assert_not_called()
            deliver.assert_not_called()
            app_phone.assert_not_called()
            here.assert_not_called()
            self.assertEqual(self.commands(), [])
            self.assertIn(f'voice route ({turn}): no room it may play in; silent', self.log_text())

    def test_the_incident_with_only_nerdvana_muted(self):
        # His room muted, Labmac not (auto-mute unsure where he is): the Mac app there speaks it,
        # the muted phone doesn't, and the Mac's speakers stay quiet (the Mac app plays there).
        path = self.write_hub({'room': 'Labmac', 'phone': 'Mac', 'addresses': ['127.0.0.1:47823']},
                              levels={'Labmac': 'normal', 'Nerdvana': 'mute'},
                              phones=[self.MAC_APP, self.NERDVANA], age=2 * 60)
        routed = speak.routed(self.cfg(path), 'typed')
        self.assertEqual([(t['name'], t.get('mac_fallback')) for t in routed['targets']], [('Mac', True)])
        self.assertEqual(routed['output'], 'app-phone')

    def test_every_unmuted_device_set_to_speak(self):
        phones = [self.LAB, self.NERDVANA]
        for output, mac_silent, levels, expected in (
            ('both', False, {}, ('both', ['Lab XS', 'iPhone 16pro'], None)),
            ('both', False, {'Nerdvana': 'mute'}, ('both', ['Lab XS'], None)),
            ('both', True, {'Nerdvana': 'off'}, ('phone', ['Lab XS'], None)),
            ('app-both', True, {}, ('app-phone', ['Lab XS', 'iPhone 16pro'], None)),
            ('app-both', False, {'Lab': 'mute', 'Nerdvana': 'mute'}, ('app', [], True)),
            ('both', False, {'Lab': 'mute', 'Nerdvana': 'mute'}, ('mac', [], True)),
            ('mac', False, {'Lab': 'mute'}, ('mac', [], True)),
            ('app', False, {}, ('app', [], True)),
            ('phone', False, {'Lab': 'mute', 'Nerdvana': 'mute'}, None),
            ('app-phone', False, {'Lab': 'mute', 'Nerdvana': 'mute'}, None),
            ('mac', True, {}, None),
            ('app', True, {}, None),
        ):
            path = self.write_hub(None, levels=levels, mac_silent=mac_silent, phones=phones)
            for turn in ('typed', 'notice'):
                routed = speak.routed(self.cfg(path, output), turn)
                got = None if routed.get('silent') else \
                    (routed['output'], [t['name'] for t in routed.get('targets', [])], routed.get('on_mac'))
                self.assertEqual(got, expected, (output, mac_silent, levels, turn))

    def test_the_room_he_is_in(self):
        # Auto-mute: the rooms he isn't in are muted, so D reaches only his room's devices.
        path = self.write_hub(None, levels={'Lab': 'mute', 'Nerdvana': 'normal'}, mac_silent=True,
                              phones=[self.LAB, self.NERDVANA])
        run, deliver = self.run_speaker(self.cfg(path, 'both'), prompted=False)
        self.assertEqual(self.spoken(run), [])
        self.assertEqual([t['name'] for t in deliver.call_args[0][0]['targets']], ['iPhone 16pro'])

    def test_malformed_levels_never_raise(self):
        state = os.path.join(self.dir.name, 'eyes-ears')
        os.makedirs(state, exist_ok=True)
        path = os.path.join(state, 'voice-route.json')
        with open(os.path.join(state, 'status.json'), 'w') as f:
            f.write('{}')
        for shape in ({'level': 5, 'levels': [1], 'mac_silent': 'yes'}, {'levels': {'Lab': 3, 7: 'mute'}},
                      {'level': None, 'phones': [{'name': 'x', 'room': 5, 'addresses': ['1.2.3.4:5'], 'silent': 'y'}]},
                      {'level': 'mute', 'room': ['Lab'], 'addresses': ['1.2.3.4:5'], 'at_unix': speak.time.time()}):
            with open(path, 'w') as f:
                json.dump(shape, f)
            for turn in ('heard', 'typed', 'notice'):
                speak.routed(self.cfg(path), turn)


class VoiceRulesFollowUp(SpeakerTests):
    """The skeptic's findings on the first round (2026-10-17), with hub 0.2.36's "mac_rooms" and
    "his_room": a heard line's reply belongs to the room its 👂 label names, never to a route
    from another room; the Mac's speakers count in every room they are in; and rule D goes to the
    room he is in when the hub knows it."""

    LAB, NERDVANA, MAC_APP = VoiceRules.LAB, VoiceRules.NERDVANA, VoiceRules.MAC_APP
    write_hub, commands, cfg = VoiceRules.write_hub, VoiceRules.commands, VoiceRules.cfg

    def heard_from(self, *rooms):
        with open(speak.LAST_PROMPT, 'w') as f:
            json.dump({'heard': True, 'rooms': list(rooms), 'at_unix': speak.time.time()}, f)

    LAB_ROUTE = {'room': 'Lab', 'phone': 'Lab XS', 'addresses': ['192.168.1.40:47811'], 'fallback': 'stream_only'}

    def test_a_late_line_from_a_muted_room_is_never_answered_aloud_elsewhere(self):
        # The HIGH finding: "👂 Nerdvana (late, 13:40): …" renews no route; the Lab's, 2 minutes
        # old, pointed at the Lab XS, and her reply played there.
        path = self.write_hub(self.LAB_ROUTE, levels={'Lab': 'normal', 'Nerdvana': 'mute'},
                              phones=[self.LAB, self.NERDVANA], age=2 * 60)
        speak.note_prompt('👂 Nerdvana (late, 13:40): Sakamoto, which one was it?')
        with mock.patch.object(speak, 'app_phone') as app_phone, mock.patch.object(speak, 'app_read_here') as here:
            run, deliver = self.run_speaker(self.cfg(path), text='The second one.\n13:42', turn='heard')
        run.assert_not_called()
        deliver.assert_not_called()
        app_phone.assert_not_called()
        here.assert_not_called()
        self.assertEqual(self.commands(), [{'cmd': 'silent_reply', 'room': 'Nerdvana', 'text': 'The second one.\n13:42'}])
        self.assertIn('voice route (heard): Nerdvana is muted; silent everywhere; shown there', self.log_text())

    def test_a_late_line_from_a_room_that_is_not_muted_is_answered_there(self):
        path = self.write_hub(self.LAB_ROUTE, levels={'Lab': 'normal', 'Nerdvana': 'normal'},
                              phones=[self.LAB, self.NERDVANA], age=2 * 60)
        self.heard_from('Nerdvana')
        routed = speak.routed(self.cfg(path), 'heard')
        self.assertEqual([t['name'] for t in routed['targets']], ['iPhone 16pro'])
        self.assertEqual(routed['output'], 'app-phone')
        # The route's own room: the route, as before.
        self.heard_from('Lab')
        self.assertEqual([t['name'] for t in speak.routed(self.cfg(path), 'heard')['targets']], ['Lab XS'])
        # No device in the line's room, the Mac's speakers elsewhere: silent (the text is on screen).
        path = self.write_hub(self.LAB_ROUTE, phones=[self.LAB], mac_rooms=['Labmac'])
        self.heard_from('Nerdvana')
        self.assertTrue(speak.routed(self.cfg(path), 'heard').get('silent'))

    def test_a_line_heard_in_two_rooms_one_muted(self):
        path = self.write_hub(self.LAB_ROUTE, levels={'Lab': 'normal', 'Nerdvana': 'off'}, phones=[self.LAB, self.NERDVANA])
        self.heard_from('Lab', 'Nerdvana')
        routed = speak.routed(self.cfg(path), 'heard')
        self.assertEqual((routed.get('silent_in'), routed.get('silent_rooms')), ('Nerdvana', ['Nerdvana']))

    def test_a_route_to_the_macs_speakers_in_a_muted_room(self):
        # The Mac app in Labmac (the route's room) and mac_voice_rooms' Lab: the Lab muted, so the
        # Mac's speakers are silent ("mac_silent"), though Labmac isn't.
        path = self.write_hub({'room': 'Labmac', 'addresses': [], 'mac': True}, levels={'Labmac': 'normal', 'Lab': 'mute'},
                              mac_silent=True, mac_rooms=['Lab', 'Labmac'], phones=[self.MAC_APP])
        self.heard_from('Labmac')
        with mock.patch.object(speak, 'app_read_here') as here:
            run, deliver = self.run_speaker(self.cfg(path, 'app'), turn='heard')
        run.assert_not_called()
        here.assert_not_called()
        self.assertEqual([c['room'] for c in self.commands()], ['Labmac'])

    def test_his_room_decides_what_no_room_asked_for(self):
        # The coordinator's decision for rule D: auto-mute knows his room: only there.
        phones = [self.LAB, self.NERDVANA, self.MAC_APP]
        path = self.write_hub(None, levels={'Lab': 'mute', 'Labmac': 'mute', 'Nerdvana': 'normal'}, mac_silent=True,
                              mac_rooms=['Labmac'], his_room='Nerdvana', phones=phones)
        for turn in ('typed', 'notice'):
            routed = speak.routed(self.cfg(path, 'both'), turn)
            self.assertEqual(([t['name'] for t in routed['targets']], routed['output']), (['iPhone 16pro'], 'phone'), turn)
        # His room is the Lab, where the Mac's speakers are (Labmac auto-muted for it: no matter).
        path = self.write_hub(None, levels={'Lab': 'normal', 'Labmac': 'mute', 'Nerdvana': 'mute'}, mac_silent=False,
                              mac_rooms=['Lab', 'Labmac'], his_room='Lab', phones=[self.LAB, self.NERDVANA])
        routed = speak.routed(self.cfg(path, 'both'), 'notice')
        self.assertEqual(([t['name'] for t in routed['targets']], routed['output']), (['Lab XS'], 'both'))
        # His room muted by hand: nowhere, not the other rooms.
        path = self.write_hub(None, levels={'Lab': 'normal', 'Nerdvana': 'mute'}, his_room='Nerdvana',
                              mac_rooms=['Lab'], phones=[self.LAB, self.NERDVANA])
        self.assertTrue(speak.routed(self.cfg(path, 'both'), 'typed').get('silent'))
        # His room unknown: every room that isn't muted, as before.
        path = self.write_hub(None, levels={'Lab': 'normal', 'Nerdvana': 'mute'}, mac_rooms=['Lab'],
                              phones=[self.LAB, self.NERDVANA])
        routed = speak.routed(self.cfg(path, 'both'), 'typed')
        self.assertEqual(([t['name'] for t in routed['targets']], routed['output']), (['Lab XS'], 'both'))

    def test_her_time_after_an_emoji_makes_no_sound(self):
        with mock.patch.object(speak, 'launch') as launch, \
             mock.patch.object(sys, 'stdin', io.StringIO(json.dumps({'last_assistant_message': '👍\n13:40'}))), \
             mock.patch.object(sys, 'argv', ['speak.py']):
            self.write_config({'enabled': True})
            speak.main()
        launch.assert_not_called()
        self.assertIn('response: nothing to say', self.log_text())


class TurnKinds(Isolated):
    """Which kind of turn a response ends: a reply to a 👂 line, to a typed prompt, or none."""

    def test_heard_rooms(self):
        self.assertEqual(speak.heard_rooms('👂 Lab: Miss Sakamoto, hello'), ['Lab'])
        self.assertEqual(speak.heard_rooms('👂 Lab + Den: what time is it?'), ['Lab', 'Den'])
        self.assertEqual(speak.heard_rooms('👂 Lab (late, 14:12): hello'), ['Lab'])
        self.assertIsNone(speak.heard_rooms('Miss Sakamoto, the ear 👂: is it on?'))
        self.assertIsNone(speak.heard_rooms(None))

    def run_stop(self, prompt):
        with mock.patch.object(speak, 'hook_prompt', return_value=prompt), mock.patch.object(speak, 'exchange'), \
             mock.patch.object(sys, 'argv', ['speak.py', 'stop']), redirect_stdout(io.StringIO()):
            speak.main()

    def test_the_prompt_decides(self):
        self.run_stop('👂 Lab: Miss Sakamoto, what time is it?')
        self.assertEqual(speak.turn_kind(True), 'heard')
        self.run_stop('Okay, try it now.')
        self.assertEqual(speak.turn_kind(True), 'typed')
        self.assertEqual(speak.turn_kind(False), 'notice')

    def test_a_notice_is_not_a_prompt(self):
        self.run_stop('👂 Lab: hello')
        self.run_stop('<task-notification>\n<task-id>x</task-id>')
        self.assertEqual(speak.turn_kind(True), 'heard')         # unchanged
        self.assertIn('a notice (task-notification)', self.log_text())

    def test_nothing_known_counts_as_typed(self):
        self.assertEqual(speak.turn_kind(True), 'typed')

    def test_the_speaker_gets_the_turn(self):
        with mock.patch.object(speak.subprocess, 'Popen') as popen:
            speak.launch('Hi.', prompted=True, turn='heard')
        self.assertEqual(popen.call_args[0][0][-2:], ['--turn', 'heard'])


class TapToSeveralPhones(FakeToolCase):
    """Tap.relay with several phones: one that ends its stream is dropped, the others go on."""

    def test_one_phone_closing_leaves_the_other(self):
        tap = self.tap('ok')
        self.assertTrue(tap.wait_ready())
        a, a_phone = socket.socketpair()
        b, b_phone = socket.socketpair()
        for s in (a, a_phone, b, b_phone):
            self.addCleanup(s.close)
        a_phone.close()
        received = bytearray()
        reader = drain(b_phone, received)
        live = [a, b]
        self.assertIsNone(tap.relay(live, timeout=10))
        self.assertEqual(live, [b])
        self.assertEqual(tap.stop(), 0)
        speak.end_stream(b)
        reader.join(5)
        self.assertEqual(bytes(received), AUDIO)
        self.assertIn('one phone of several: the phone ended the stream', self.log_text())


# ---- The phone chooses: Claude's voice or the text (phone_voice) ----------------------------

WANTS_TEXT = {'ok': False, 'want': 'text', 'voice': 'text', 'app': 'Sakamoto Voice', 'version': '1.0'}


class NoteVoiceTests(Isolated):
    """phone_voice is kept from every answer the phone gives."""

    def test_the_phone_says(self):
        for ack, kept in (({'ok': True, 'voice': 'text'}, 'text'), ({'ok': True, 'voice': 'stream'}, 'stream'),
                          (WANTS_TEXT, 'text'), ({'ok': False, 'want': 'text'}, 'text'),
                          ({'ok': False, 'error': 'no text', 'voice': 'stream'}, 'stream')):
            with self.subTest(ack=ack):
                self.write_config({'phone_voice': 'text' if kept == 'stream' else 'stream'})
                self.assertEqual(speak.note_voice(ack), kept)
                self.assertEqual(self.read_config()['phone_voice'], kept)

    def test_an_old_phone_counts_as_stream(self):
        self.write_config({'phone_voice': 'text'})
        self.assertEqual(speak.note_voice({'ok': True, 'app': 'Sakamoto Voice', 'version': '0.3.1'}), 'stream')
        self.assertEqual(self.read_config()['phone_voice'], 'stream')

    def test_refusals_that_do_not_say_change_nothing(self):
        self.write_config({'phone_voice': 'text'})
        for ack in ({'ok': False, 'error': 'bad token'}, {}, None, [], {'ok': False, 'voice': 'mp3'}):
            with self.subTest(ack=ack):
                self.assertIsNone(speak.note_voice(ack))
        self.assertEqual(self.read_config()['phone_voice'], 'text')

    def test_unknown_until_the_phone_answers_and_logged_only_on_a_change(self):
        self.assertEqual(speak.config()['phone_voice'], '')
        speak.note_voice({'ok': True, 'voice': 'text'})
        speak.note_voice({'ok': True, 'voice': 'text'})
        self.assertEqual(self.log_text().count('wants the text'), 1)


class PhoneVoiceOverTheWireTests(FakeToolCase):
    """The answers that set phone_voice, from stand-in phones on the loopback interface."""

    def stub(self, reply):
        try:
            phone = ServerStub(reply)
        except OSError as e:
            self.skipTest(f'cannot listen here: {e}')
        self.addCleanup(phone.close)
        return phone

    def test_a_ping_answer_is_kept(self):
        phone = self.stub({'ok': True, 'app': 'Sakamoto Voice', 'version': '1.0', 'voice': 'text'})
        self.write_config({'phone_token': '123456', 'phone': phone.address})
        self.assertTrue(speak.send_to_phone(speak.message('123456', 'ping'))['ok'])
        self.assertEqual(self.read_config()['phone_voice'], 'text')

    def test_a_stop_answer_is_kept(self):
        phone = self.stub({'ok': True, 'app': 'Sakamoto Voice', 'version': '1.0', 'voice': 'stream'})
        self.write_config({'phone_token': '123456', 'phone': phone.address, 'output': 'app-phone', 'phone_voice': 'text'})
        speak.stop_phone(speak.config())
        self.assertEqual(phone.received[0]['kind'], 'stop')
        self.assertEqual(self.read_config()['phone_voice'], 'stream')

    def test_a_declined_stream_is_kept_and_the_text_is_sent(self):
        try:
            phone = StreamPhone(WANTS_TEXT)
        except OSError as e:
            self.skipTest(f'cannot listen here: {e}')
        self.addCleanup(phone.close)
        sock, ack = speak.open_stream(phone.address, speak.stream_header('123456', 'Hi'))
        sock.close()
        self.assertEqual((ack['ok'], ack['want']), (False, 'text'))
        self.assertEqual(self.read_config()['phone_voice'], 'text')

        # All of app-phone against it: no tap, no click, the text instead.
        cfg = dict(speak.DEFAULTS, output='app-phone', phone_token='123456', phone=phone.address)
        self.write_config(cfg)
        with self.mode('ok'), \
             mock.patch.object(speak, 'tap_path', return_value=self.tool), \
             mock.patch.object(speak, 'Tap') as tap, \
             mock.patch.object(speak, 'app_read') as click, \
             mock.patch.object(speak, 'deliver_to_phone') as deliver:
            self.assertIsNone(speak.app_phone(cfg, 'Hello', 'Hello', [('default', 'Hello')], [('en', 'Hello')], set()))
        tap.assert_not_called()
        click.assert_not_called()
        self.assertEqual(deliver.call_args[0][0]['phone_mode'], 'text')
        self.assertEqual(self.read_config()['phone_voice'], 'text')
        self.assertIn('app-phone: the phone wants the text, not the stream', self.log_text())
        self.assertEqual(phone.audio, [])


class DeclinedStreamTests(Isolated):
    """app_phone() when the phone answers the header with "want": "text"."""

    CFG = AppPhoneTests.CFG
    run_app_phone = AppPhoneTests.run_app_phone
    assert_text_fallback = AppPhoneTests.assert_text_fallback

    def test_app_phone_sends_the_text(self):
        tap, _, click, deliver = self.run_app_phone(opened=dict(WANTS_TEXT))
        self.assertFalse(hasattr(tap, 'path'))           # no tap started
        click.assert_not_called()
        self.sock.close.assert_called()
        self.assert_text_fallback(deliver)
        self.assertIn('wants the text, not the stream', self.log_text())
        self.assertNotIn('nothing read aloud', self.log_text())

    def test_app_both_hands_back_before_the_click(self):
        with mock.patch.object(speak, 'tap_path', return_value='/bin/app-voice-tap'), \
             mock.patch.object(speak, 'Tap', FakeTap()) as tap, \
             mock.patch.object(speak, 'reach_phone', return_value=(mock.Mock(), dict(WANTS_TEXT))), \
             mock.patch.object(speak, 'app_read') as click, \
             mock.patch.object(speak, 'deliver_to_phone') as deliver:
            self.write_config(self.CFG)
            stage = speak.app_phone(self.CFG, 'Hi', 'Hi', [('default', 'Hi')], [('en', 'Hi')], set(), both=True)
        self.assertEqual(stage, 'before-click')          # the caller: the app's voice here, the text there
        self.assertFalse(hasattr(tap, 'path'))
        click.assert_not_called()
        deliver.assert_not_called()


class PhoneVoiceRoutingTests(Isolated):
    """speak()'s choices for app-phone and app-both, by the remembered phone_voice."""

    run_speaker = SpeakerTests.run_speaker

    def test_app_phone_with_text_remembered_skips_the_stream(self):
        with mock.patch.object(speak, 'app_phone') as app_phone, mock.patch.object(speak, 'app_read') as click:
            run, deliver = self.run_speaker({'output': 'app-phone', 'phone_voice': 'text', 'phone_mode': 'audio'})
        app_phone.assert_not_called()
        click.assert_not_called()
        run.assert_not_called()                          # the Mac stays silent
        cfg, text, runs, _, _ = deliver.call_args[0]
        self.assertEqual((cfg['phone_mode'], text, runs), ('text', 'Hello 囲碁', [('default', 'Hello'), ('ja', '囲碁')]))
        self.assertIn('app-phone: the phone wants the text; sending it, no stream', self.log_text())

    def test_app_phone_streams_when_stream_or_unknown(self):
        for remembered in ('stream', '', None):
            with self.subTest(phone_voice=remembered), mock.patch.object(speak, 'app_phone') as app_phone:
                cfg = {'output': 'app-phone'} | ({} if remembered is None else {'phone_voice': remembered})
                _, deliver = self.run_speaker(cfg)
            app_phone.assert_called_once()
            deliver.assert_not_called()

    def test_app_both_with_text_remembered_reads_here_and_sends_the_text(self):
        with mock.patch.object(speak, 'app_phone') as app_phone, \
             mock.patch.object(speak, 'app_read', return_value=True) as click:
            run, deliver = self.run_speaker({'output': 'app-both', 'phone_voice': 'text', 'default_lang': 'en'})
        app_phone.assert_not_called()                    # no tap, no stream
        click.assert_called_once()                       # the app's voice on the Mac, unmuted
        run.assert_not_called()
        deliver.assert_called_once()                     # the text to the phone
        self.assertIn("app-both: the phone wants the text; the app's voice here", self.log_text())

    def test_app_both_with_text_remembered_and_the_debugger_off(self):
        with mock.patch.object(speak, 'app_phone') as app_phone, \
             mock.patch.object(speak, 'app_read', return_value=False):
            run, deliver = self.run_speaker({'output': 'app-both', 'phone_voice': 'text', 'default_lang': 'en'})
        app_phone.assert_not_called()
        self.assertEqual(run.call_count, 2)              # the Mac's own voices
        deliver.assert_called_once()

    def test_app_both_streams_when_stream_remembered(self):
        with mock.patch.object(speak, 'app_phone', return_value=None) as app_phone:
            run, deliver = self.run_speaker({'output': 'app-both', 'phone_voice': 'stream', 'default_lang': 'en'})
        self.assertTrue(app_phone.call_args.kwargs['both'])
        run.assert_not_called()
        deliver.assert_not_called()

    def test_other_outputs_ignore_it(self):
        run, deliver = self.run_speaker({'output': 'both', 'phone_voice': 'text', 'default_lang': 'en'})
        self.assertEqual(run.call_count, 2)
        deliver.assert_called_once()


class Recordings(Isolated):
    """The last two streamed readings are kept, with their text."""

    def test_rotation_keeps_two(self):
        for n in (1, 2, 3):
            path = speak.recording_path(f'reply {n}')
            with wave.open(path, 'wb') as w:
                w.setnchannels(1); w.setsampwidth(2); w.setframerate(speak.STREAM_RATE)
                w.writeframes(b'\0\0' * n)
        names = sorted(os.listdir(speak.RECORDINGS))
        self.assertEqual(names, ['latest.txt', 'latest.wav', 'previous.txt', 'previous.wav'])
        with open(os.path.join(speak.RECORDINGS, 'latest.txt'), encoding='utf-8') as f:
            self.assertTrue(f.read().endswith('reply 3'))
        with wave.open(os.path.join(speak.RECORDINGS, 'previous.wav')) as w:
            self.assertEqual(w.getnframes(), 2)


class Notices(unittest.TestCase):
    def test_is_notice(self):
        self.assertTrue(speak.is_notice('<task-notification>\n<task-id>x</task-id>'))
        self.assertTrue(speak.is_notice('  <system-reminder>hi'))
        self.assertFalse(speak.is_notice('Okay, try it now.'))
        self.assertFalse(speak.is_notice('I love <b>tags</b>'))


class VoiceRace(Isolated):
    """2026-10-14 06:25 and 14:35: "app: no matching message; the newest holds …", then the phone's
    own voice, after a tool-heavy turn and for a reply with a code block. app_read looks again for
    a few seconds, and the key and the page's text both leave code blocks out."""

    def run_app_read(self, outputs, text='14:35 Here it is.'):
        results = [mock.Mock(returncode=0 if out.startswith('clicked') else 1, stdout=out, stderr='') for out in outputs]
        with mock.patch.object(speak.shutil, 'which', return_value='/usr/local/bin/node'), \
             mock.patch.object(speak.subprocess, 'run', side_effect=results) as run:
            return speak.app_read(text, delay=0), run

    def test_it_looks_again_when_no_message_matched(self):
        clicked, run = self.run_app_read(['no matching message; the newest holds 300 chars: shprivatetmp',
                                          'clicked (at 0 of 20)'])
        self.assertTrue(clicked)
        self.assertEqual(run.call_count, 2)
        self.assertEqual(run.call_args_list[0].args[0][-1], str(int(speak.APP_READ_WAIT * 1000)))
        self.assertEqual(run.call_args_list[1].args[0][-1], str(int(speak.APP_READ_RETRY * 1000)))
        self.assertTrue(os.path.exists(speak.APP_READING))
        with open(speak.LOG, encoding='utf-8') as f:
            self.assertIn('app: looking again for 6 s', f.read())

    def test_once_more_at_most(self):
        clicked, run = self.run_app_read(['no Read aloud button', 'no matching message; the newest holds 0 chars: '])
        self.assertFalse(clicked)
        self.assertEqual(run.call_count, 2)

    def test_not_for_other_reasons(self):
        for why in ('debugger not reachable (ECONNREFUSED)', 'earlier text first (40 chars before this reply: x)',
                    'already read'):
            clicked, run = self.run_app_read([why])
            self.assertFalse(clicked)
            self.assertEqual(run.call_count, 1, why)

    def test_the_tap_waits_for_both_looks(self):
        self.assertGreaterEqual(speak.TAP_WAIT_START,
                                speak.APP_READ_DELAY + speak.APP_READ_WAIT + speak.APP_READ_RETRY + speak.READ_LEAD)

    def test_the_key_leaves_code_blocks_out(self):
        reply = '14:35 Run this:\n\n```bash\nswift test -j 6\n```\n\nand tell me what it says.'
        self.assertEqual(speak.read_key(reply), '1435runthisandtellmewhatitsays')
        # Only code: the code is the key.
        self.assertEqual(speak.read_key('```\nls -la\n```'), 'lsla')
        # An unclosed block runs to the end.
        self.assertEqual(speak.read_key('Here:\n```\nlet x = 1'), 'here')

    def test_the_page_match(self):
        """app-read-match.mjs, through node (skipped without it)."""
        import shutil
        import subprocess
        node = shutil.which('node')
        if not node:
            self.skipTest('node not found')
        here = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'scripts', 'app-read-match.mjs')
        code = (f'import {{ norm, messageText, findKey }} from {json.dumps(os.path.abspath(here))};\n'
                'const page = "Claude responded 14:35 Run this: bash Copy swift test -j 6 and tell me what it says.";\n'
                'const text = messageText(page, ["swift test -j 6"]);\n'
                'const key = "1435runthisandtellmewhatitsays";\n'
                'console.log(JSON.stringify([text, findKey(text, key), findKey(norm("1435 Run this and tell me"), key),\n'
                '  findKey("x" + key, key), findKey("1435runthis" + "y".repeat(30) + "andtellmewhatitsays", key),\n'
                '  findKey("anything", "")]));\n')
        out = subprocess.run([node, '--input-type=module', '-e', code], capture_output=True, text=True, timeout=20)
        self.assertEqual(out.returncode, 0, out.stderr)
        text, found, partial, shifted, too_far, no_key = json.loads(out.stdout)
        self.assertEqual(text, 'clauderesponded1435runthisbashcopyandtellmewhatitsays')
        self.assertEqual(found, len('clauderesponded'))   # "bash" and "copy" among the key's letters
        self.assertEqual(partial, -1)                    # the key's end isn't there
        self.assertEqual(shifted, 1)                     # exact, after a letter
        self.assertEqual(too_far, -1)                    # more than 24 others among them
        self.assertEqual(no_key, 0)


class HubListener:
    """A stand-in for Sakamoto Eyes' hub's her-voice.sock: keeps each connection's bytes, whole."""

    def __init__(self, folder):
        self.path = os.path.join(folder, speak.VOICE_CLOCK_SOCKET)
        self.route = os.path.join(folder, 'voice-route.json')
        self.server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.server.bind(self.path)
        self.server.listen(4)
        self.received = []
        threading.Thread(target=self.serve, daemon=True).start()

    def serve(self):
        while True:
            try:
                client, _ = self.server.accept()
            except OSError:
                return
            data = bytearray()
            with client:
                while chunk := client.recv(65536):
                    data.extend(chunk)
            self.received.append(bytes(data))

    def header(self, index=0):
        return json.loads(self.received[index].split(b'\n', 1)[0])

    def audio(self, index=0):
        return self.received[index].split(b'\n', 1)[1]

    def wait(self, count, timeout=5):
        end = time.monotonic() + timeout
        while len(self.received) < count and time.monotonic() < end:
            time.sleep(0.01)
        return len(self.received) >= count

    def close(self):
        self.server.close()


class MacVoiceForTheHub(FakeToolCase):
    """Sakamoto Eyes P2.8: the hub hears of every reading on the Mac's own speakers."""

    def setUp(self):
        super().setUp()
        try:
            self.hub = HubListener(self.dir.name)
        except OSError as e:
            self.skipTest(f'cannot listen on a Unix socket here: {e}')
        self.addCleanup(self.hub.close)
        self.cfg = dict(speak.DEFAULTS, phone_route=self.hub.route)

    def test_no_hub_no_socket(self):
        self.assertIsNone(speak.hub_socket(dict(speak.DEFAULTS)))
        self.assertIsNone(speak.voice_clock(dict(speak.DEFAULTS), 'Hi', mac=True))
        self.assertEqual(speak.hub_socket(self.cfg), self.hub.path)

    def test_the_header_says_where_her_voice_plays(self):
        for count, kwargs in enumerate(({'mac': True}, {}, {'mac': True, 'audio': False}), start=1):
            speak.voice_clock(self.cfg, 'Hi', **kwargs).close()
            self.assertTrue(self.hub.wait(count))
        self.assertEqual(self.hub.header(0), {'text': 'Hi', 'rate': speak.STREAM_RATE, 'format': 'pcm16',
                                              'channels': 1, 'mac': True})
        self.assertFalse(self.hub.header(1)['mac'])
        self.assertNotIn('audio', self.hub.header(1))
        self.assertEqual((self.hub.header(2)['mac'], self.hub.header(2)['audio']), (True, False))

    def test_the_header_names_the_phones_streamed_to(self):
        speak.voice_clock(self.cfg, 'Hi', mac=True, phones=['iPhone 16 Pro']).close()
        self.assertTrue(self.hub.wait(1))
        self.assertEqual(self.hub.header(0)['phones'], ['iPhone 16 Pro'])
        speak.voice_clock(self.cfg, 'Hi').close()
        self.assertTrue(self.hub.wait(2))
        self.assertNotIn('phones', self.hub.header(1))

    def test_a_relay_to_no_phone_feeds_the_copy_only(self):
        tap = self.tap('ok')
        self.assertTrue(tap.wait_ready())
        self.assertIsNone(tap.relay([], timeout=10, copy=speak.voice_clock(self.cfg, 'Hi', mac=True)))
        self.assertEqual(tap.stop(), 0)
        self.assertTrue(self.hub.wait(1))
        self.assertEqual(self.hub.audio(), AUDIO)
        self.assertAlmostEqual(tap.seconds, len(AUDIO) / 48000)

    def test_the_apps_voice_on_the_mac_alone_is_tapped_unmuted_for_the_hub(self):
        with self.mode('ok'), mock.patch.object(speak, 'tap_path', return_value=self.tool), \
             mock.patch.object(speak, 'app_read', return_value=True) as click:
            follow = speak.app_read_here(self.cfg, 'Hello there')
            self.assertIsNotNone(follow)
            follow()
        click.assert_called_once()
        self.assertNotIn('--mute', self.read('args').split('\n'))        # the Mac plays it
        self.assertTrue(self.hub.wait(1))
        self.assertEqual(self.hub.header(), {'text': 'Hello there', 'rate': speak.STREAM_RATE, 'format': 'pcm16',
                                             'channels': 1, 'mac': True})
        self.assertEqual(self.hub.audio(), AUDIO)
        self.assertIn('app (Mac): 1.0 s for the hub', self.log_text())

    def test_not_clicked_follows_nothing(self):
        with self.mode('hang'), mock.patch.object(speak, 'tap_path', return_value=self.tool), \
             mock.patch.object(speak, 'app_read', return_value=False):
            self.assertIsNone(speak.app_read_here(self.cfg, 'Hello'))
        time.sleep(0.1)
        self.assertEqual(self.hub.received, [])

    def test_without_the_tool_a_note_for_the_estimated_length(self):
        with mock.patch.object(speak, 'tap_path', return_value=None), \
             mock.patch.object(speak, 'app_read', return_value=True), \
             mock.patch.object(speak, 'reading_seconds', return_value=speak.READ_LEAD + 0.2):
            speak.app_read_here(self.cfg, 'Hello')()
        self.assertTrue(self.hub.wait(1))
        self.assertEqual((self.hub.header()['mac'], self.hub.header()['audio']), (True, False))
        self.assertEqual(self.hub.audio(), b'')

    def test_without_a_hub_only_the_click(self):
        with mock.patch.object(speak, 'tap_path') as tap_path, \
             mock.patch.object(speak, 'app_read', return_value=True):
            speak.app_read_here(dict(speak.DEFAULTS), 'Hello')()
        tap_path.assert_not_called()
        with mock.patch.object(speak, 'app_read', return_value=False):
            self.assertIsNone(speak.app_read_here(dict(speak.DEFAULTS), 'Hello'))

    def test_say_on_the_mac_is_a_note_while_it_speaks(self):
        self.write_config(dict(self.cfg, output='mac', default_lang='en'))
        fd, path = tempfile.mkstemp(dir=self.dir.name)
        with os.fdopen(fd, 'w') as f:
            f.write('Hello there')
        spoke = []

        def say(argv, **kwargs):
            spoke.append((argv[-1], len(self.hub.received)))       # the note is still open
        with mock.patch.object(speak, 'installed_voices', return_value=set()), \
             mock.patch.object(speak.subprocess, 'run', side_effect=say):
            speak.speak(path)
        self.assertTrue(self.hub.wait(1))
        self.assertEqual(spoke, [('Hello there', 0)])
        self.assertEqual(self.hub.header(), {'text': 'Hello there', 'rate': speak.STREAM_RATE, 'format': 'pcm16',
                                             'channels': 1, 'mac': True, 'audio': False})

    def test_app_both_tells_the_hub_the_mac_plays(self):
        with mock.patch.object(speak, 'tap_path', return_value='/bin/app-voice-tap'), \
             mock.patch.object(speak, 'Tap', FakeTap()), \
             mock.patch.object(speak, 'reach_phone', return_value=(mock.Mock(), {'ok': True})), \
             mock.patch.object(speak, 'open_stream'), mock.patch.object(speak, 'end_stream'), \
             mock.patch.object(speak, 'app_read', return_value=True), \
             mock.patch.object(speak, 'voice_clock', return_value=None) as clock:
            cfg = dict(self.cfg, output='app-both', phone_token='123456')
            self.write_config(cfg)
            speak.app_phone(cfg, 'Hi', 'Hi', [('default', 'Hi')], [('en', 'Hi')], set(), both=True)
            speak.app_phone(cfg, 'Hi', 'Hi', [('default', 'Hi')], [('en', 'Hi')], set())
        self.assertEqual([c.kwargs.get('mac') for c in clock.call_args_list], [True, False])

    def test_app_output_follows_the_reading_after_the_click(self):
        order = []
        self.write_config(dict(self.cfg, output='app', default_lang='en'))
        fd, path = tempfile.mkstemp(dir=self.dir.name)
        with os.fdopen(fd, 'w') as f:
            f.write('Hello')
        with mock.patch.object(speak, 'installed_voices', return_value=set()), \
             mock.patch.object(speak.subprocess, 'run') as run, \
             mock.patch.object(speak, 'app_read_here', return_value=lambda: order.append('followed')):
            speak.speak(path)
        run.assert_not_called()
        self.assertEqual(order, ['followed'])
