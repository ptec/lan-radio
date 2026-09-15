import queue
import threading
import unittest
from radio.web import buffered_audio


class StreamBufferingTests(unittest.TestCase):
    def test_first_response_waits_for_audio_then_continues_without_rebuffering(self):
        listener = queue.Queue()
        stop = threading.Event()
        # Eight distinct chunks represent two seconds of 128 kbps audio.
        chunks = [bytes([n]) * 4000 for n in range(8)]
        for chunk in chunks[:-1]:
            listener.put(chunk)
        stream = buffered_audio(listener, stop)
        result = []
        started, received = threading.Event(), threading.Event()
        def read_first():
            started.set()
            result.append(next(stream))
            received.set()
        reader = threading.Thread(target=read_first)
        reader.start()
        try:
            self.assertTrue(started.wait(1))
            self.assertFalse(received.wait(.1), 'Audio was sent before the startup buffer filled')
            listener.put(chunks[-1])
            self.assertTrue(received.wait(1))
            reader.join(1)
            self.assertEqual(result, [b''.join(chunks)])
            listener.put(b'next live chunk')
            self.assertEqual(next(stream), b'next live chunk')
        finally:
            stop.set()
            listener.put(None)
            reader.join(2)
            stream.close()

    def test_disconnect_during_buffering_does_not_flush_partial_audio(self):
        listener = queue.Queue()
        listener.put(b'partial audio')
        listener.put(None)
        self.assertEqual(list(buffered_audio(listener, threading.Event())), [])

    def test_each_new_connection_gets_its_own_buffer(self):
        streams = []
        for value in (b'a', b'b'):
            listener = queue.Queue()
            listener.put(value * 33000)
            listener.put(None)
            streams.append(list(buffered_audio(listener, threading.Event())))
        self.assertEqual(streams, [[b'a' * 33000], [b'b' * 33000]])


if __name__ == '__main__':
    unittest.main()
