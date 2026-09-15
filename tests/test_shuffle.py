import random
import unittest
from radio.audio import ShuffleRotation


def songs(count):
    return [dict(id=str(i), title=f'Song {i}', artist='Artist') for i in range(count)]


class ShuffleTests(unittest.TestCase):
    def test_complete_cycles_and_no_boundary_repeat_across_many_seeds(self):
        for count in (2, 3, 10):
            library = songs(count)
            for seed in range(30):
                rotation = ShuffleRotation(random.Random(seed))
                previous = None
                orders = []
                for _ in range(20):
                    cycle = []
                    for _ in library:
                        preview = rotation.peek(library)
                        self.assertEqual(preview, rotation.peek(library))
                        actual = rotation.take(library)
                        self.assertEqual(actual, preview)
                        self.assertNotEqual(actual['id'], previous)
                        previous = actual['id']
                        cycle.append(previous)
                    self.assertEqual(set(cycle), {s['id'] for s in library})
                    orders.append(tuple(cycle))
                if count > 2:
                    self.assertGreater(len(set(orders)), 1)

    def test_additions_join_current_cycle_without_replaying_consumed_songs(self):
        library = songs(4)
        rotation = ShuffleRotation(random.Random(7))
        first = rotation.take(library[:3])
        rest = [rotation.take(library)['id'] for _ in range(3)]
        self.assertNotIn(first['id'], rest)
        self.assertEqual(set(rest + [first['id']]), {s['id'] for s in library})

    def test_removal_and_reordering_do_not_reset_remaining_cycle(self):
        library = songs(5)
        rotation = ShuffleRotation(random.Random(3))
        first = rotation.take(library)
        removed = rotation.peek(library)
        remaining = [s for s in reversed(library) if s != removed]
        played = [rotation.take(remaining)['id'] for _ in range(3)]
        self.assertNotIn(first['id'], played)
        self.assertNotIn(removed['id'], played)
        self.assertEqual(len(set(played)), 3)

    def test_duplicate_rows_share_one_slot(self):
        library = songs(2)
        library.append(dict(library[0], id='duplicate-row'))
        rotation = ShuffleRotation(random.Random(1))
        titles = [rotation.take(library)['title'] for _ in range(6)]
        self.assertTrue(all(a != b for a, b in zip(titles, titles[1:])))

    def test_empty_and_single_song(self):
        rotation = ShuffleRotation(random.Random(1))
        self.assertIsNone(rotation.take([]))
        for _ in range(3):
            self.assertEqual(rotation.take(songs(1))['id'], '0')
        self.assertIsNone(rotation.peek([]))


if __name__ == '__main__':
    unittest.main()
