import io
import unittest
from r3_raw_source_probe import BoundedReader


class ReaderTests(unittest.TestCase):
    def test_budget_and_negative_read(self):
        reader=BoundedReader(io.BytesIO(b'12345'),4)
        self.assertEqual(reader.read(2),b'12')
        with self.assertRaises(ValueError): reader.read(3)
        with self.assertRaises(ValueError): reader.read(-1)
        self.assertEqual(reader.received,2)


if __name__=='__main__': unittest.main()
