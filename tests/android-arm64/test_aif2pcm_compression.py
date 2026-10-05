"""Run the production AIFF converter across partial BDPCM block boundaries."""

from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
DELTAS = (0, 1, 4, 9, 16, 25, 36, 49, -64, -49, -36, -25, -16, -9, -4, -1)


def aiff(samples, declared_count=None, loop=None):
    """An 8-bit mono AIFF with a 16384 Hz extended precision sample rate."""
    def chunk(name, body):
        return name + struct.pack('>I', len(body)) + body + bytes(len(body) % 2)
    if declared_count is None:
        declared_count = len(samples)
    comm = struct.pack('>HIH', 1, declared_count, 8) + bytes.fromhex('400d8000000000000000')
    body = b'AIFF' + chunk(b'COMM', comm)
    if loop is not None:
        markers = struct.pack('>H', 2)
        for marker, position in enumerate(loop, 1):
            markers += struct.pack('>HI', marker, position) + bytes(2)
        instrument = struct.pack('>6Bh6H', 60, 0, 0, 127, 1, 127, 0,
                                 1, 1, 2, 0, 0, 0)
        body += chunk(b'MARK', markers) + chunk(b'INST', instrument)
    body += chunk(b'SSND', bytes(8) + samples)
    return b'FORM' + struct.pack('>I', len(body)) + body


def decode(payload, count):
    """Decode only stored samples, independently of the C converter."""
    output = bytearray()
    position = 0
    while len(output) < count:
        remaining = min(64, count - len(output))
        value = payload[position]
        position += 1
        output.append(value)
        if remaining > 1:
            value = (value + DELTAS[payload[position] & 15]) & 255
            position += 1
            output.append(value)
        for index in range(2, remaining, 2):
            packed = payload[position]
            position += 1
            value = (value + DELTAS[packed >> 4]) & 255
            output.append(value)
            if index + 1 < remaining:
                value = (value + DELTAS[packed & 15]) & 255
                output.append(value)
    if position != len(payload):
        raise AssertionError(f'Unconsumed encoded bytes: {len(payload) - position}')
    return bytes(output)


@unittest.skipUnless(shutil.which('gcc'), 'GCC required to build the production converter')
class Aif2PcmCompressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.directory = Path(cls.temp.name)
        cls.converter = cls.directory / 'aif2pcm'
        subprocess.run(['gcc', '-std=gnu11', '-O2',
                        str(ROOT / 'tools/aif2pcm/main.c'),
                        str(ROOT / 'tools/aif2pcm/extended.c'),
                        '-lm', '-o', str(cls.converter)], check=True)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def convert(self, samples, compressed=True, declared_count=None, loop=None):
        source = self.directory / 'sample.aif'
        target = self.directory / 'sample.bin'
        source.write_bytes(aiff(samples, declared_count, loop))
        command = [str(self.converter), str(source), str(target)]
        if compressed:
            command.append('--compress')
        subprocess.run(command, check=True)
        data = target.read_bytes()
        logical_count = len(samples) if declared_count is None else declared_count
        if loop is not None:
            logical_count = loop[1]
        logical_count = min(logical_count, len(samples))
        self.assertEqual(struct.unpack_from('<IIII', data),
                         (int(compressed) | (0x40000000 if loop else 0),
                          16384 * 1024, loop[0] if loop else 0, logical_count - 1))
        return data[16:]

    @staticmethod
    def samples(count):
        # Every delta is exactly representable (+1 or -1), including the
        # final high nibble, so dropping it also changes decoded audio.
        return bytes((index % 64 if index % 64 <= 32 else 64 - index % 64)
                     for index in range(count))

    def check_compressed(self, count):
        samples = self.samples(count)
        encoded = self.convert(samples)
        blocks, tail = divmod(count, 64)
        tail_bytes = (2 + (tail - 1) // 2) if tail >= 2 else tail
        self.assertEqual(len(encoded), blocks * 33 + tail_bytes)
        self.assertEqual(decode(encoded, count), samples)

    def test_odd_partial_blocks_keep_final_high_nibble(self):
        for count in (3, 5, 31, 63, 67, 127, 8533):
            with self.subTest(samples=count):
                self.check_compressed(count)

    def test_even_full_and_literal_tail_blocks_are_preserved(self):
        for count in (1, 2, 38, 64, 65, 66, 128, 2150):
            with self.subTest(samples=count):
                self.check_compressed(count)

    def test_uncompressed_samples_are_preserved(self):
        for count in (3, 38, 64, 8533):
            with self.subTest(samples=count):
                samples = self.samples(count)
                self.assertEqual(self.convert(samples, compressed=False), samples)

    def test_declared_sample_count_is_bounded_by_stored_data(self):
        for compressed in (False, True):
            with self.subTest(compressed=compressed):
                samples = self.samples(38)
                encoded = self.convert(samples, compressed=compressed, declared_count=39)
                self.assertEqual(decode(encoded, len(samples)) if compressed else encoded, samples)

    def test_loop_marker_end_points_are_preserved_and_bounded(self):
        for loop in ((2, 6), (2, 9)):
            with self.subTest(loop=loop):
                samples = self.samples(8)
                encoded = self.convert(samples, declared_count=9, loop=loop)
                self.assertEqual(decode(encoded, len(samples)), samples)


if __name__ == '__main__':
    unittest.main()
