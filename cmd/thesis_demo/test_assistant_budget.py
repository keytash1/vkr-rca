import hashlib
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from assistant_budget import ENCODING_CACHE_KEY, reserve_input


class BudgetTests(unittest.TestCase):
    def test_disabled_cache_and_unavailable_tmp_never_download(self):
        tokenizer = Mock()
        with patch.dict('os.environ', {'TIKTOKEN_CACHE_DIR':''}, clear=True), patch.dict('sys.modules', {'tiktoken':tokenizer}):
            self.assertEqual(reserve_input({},'gpt-6.1-sol')[1],'UTF8_BYTES_PLUS_512_CONSERVATIVE')
        with patch.dict('os.environ', {}, clear=True), patch('assistant_budget.tempfile.gettempdir',side_effect=FileNotFoundError()), patch.dict('sys.modules', {'tiktoken':tokenizer}):
            self.assertEqual(reserve_input({},'gpt-6.1-sol')[1],'UTF8_BYTES_PLUS_512_CONSERVATIVE')
        tokenizer.get_encoding.assert_not_called()

    def test_explicit_data_gym_cache_does_not_touch_unwritable_tmp(self):
        tokenizer = SimpleNamespace(get_encoding=Mock(return_value=SimpleNamespace(encode=lambda *a,**k:[1]*10)))
        content=b'verified test cache'
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory)/ENCODING_CACHE_KEY).write_bytes(content)
            with patch.dict('os.environ', {'DATA_GYM_CACHE_DIR':directory}, clear=True), patch('assistant_budget.tempfile.gettempdir',side_effect=FileNotFoundError()), patch.dict('sys.modules', {'tiktoken':tokenizer}), patch('assistant_budget.ENCODING_SHA256',hashlib.sha256(content).hexdigest()):
                self.assertEqual(reserve_input({},'gpt-6.1-sol')[0],527)
        tokenizer.get_encoding.assert_called_once()

    def test_missing_corrupt_and_symlink_cache_do_not_call_tokenizer(self):
        tokenizer = Mock()
        with tempfile.TemporaryDirectory() as directory, patch.dict('os.environ',{'TIKTOKEN_CACHE_DIR':directory}), patch.dict('sys.modules',{'tiktoken':tokenizer}):
            path = Path(directory)/ENCODING_CACHE_KEY
            for stage in ('missing','corrupt','symlink'):
                if stage=='corrupt': path.write_bytes(b'not the verified public BPE')
                if stage=='symlink':
                    path.unlink()
                    source=Path(directory)/'other'
                    source.write_bytes(b'not followed')
                    path.symlink_to(source)
                value,method=reserve_input({'text':'учебные наблюдения'},'gpt-6.1-sol')
                self.assertGreater(value,512)
                self.assertEqual(method,'UTF8_BYTES_PLUS_512_CONSERVATIVE')
            tokenizer.get_encoding.assert_not_called()

    def test_verified_cache_uses_estimate_and_unknown_model_keeps_fallback(self):
        tokenizer = SimpleNamespace(get_encoding=Mock(return_value=SimpleNamespace(encode=lambda *a,**k:[1]*10)))
        content=b'unit cached bytes'
        with tempfile.TemporaryDirectory() as directory, patch.dict('os.environ',{'TIKTOKEN_CACHE_DIR':directory}), patch.dict('sys.modules',{'tiktoken':tokenizer}), patch('assistant_budget.ENCODING_SHA256',hashlib.sha256(content).hexdigest()):
            (Path(directory)/ENCODING_CACHE_KEY).write_bytes(content)
            value,method=reserve_input({'text':'observations'},'gpt-6.1-sol')
            self.assertEqual(value,527)
            self.assertIn('VERIFIED_LOCAL_ESTIMATE',method)
            self.assertEqual(reserve_input({'text':'observations'},'unknown')[1],'UTF8_BYTES_PLUS_512_CONSERVATIVE')
            tokenizer.get_encoding.assert_called_once()


if __name__ == '__main__': unittest.main()
