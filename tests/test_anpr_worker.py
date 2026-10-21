from pathlib import Path
import os
import tempfile
import time
import unittest
from unittest.mock import Mock
from relleno.anpr_worker import Watcher


class WatcherTests(unittest.TestCase):
    def test_only_new_stable_anpr_exports_are_added_once(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            current = time.time()
            for name, modified in [('ANPR-new.xlsx', current-30), ('ANPR-old.xlsx', current-300), ('unrelated.xlsx', current-30), ('ANPR-writing.xlsx', current)]:
                path = folder / name
                path.write_bytes(b'PK\x03\x04test-only')
                os.utime(path, (modified, modified))
            outbox = Mock()
            watcher = Watcher(outbox)
            config = {'binding': {'centre_id':'test'}, 'anpr': {'watch_enabled':True,'watch_folder':str(folder),'watch_since_ns':int((current-60)*1e9)}}
            watcher.scan(config)
            outbox.add.assert_not_called()
            watcher.scan(config)
            outbox.add.assert_called_once()
            self.assertEqual(outbox.add.call_args.args[0].name, 'ANPR-new.xlsx')
            watcher.scan(config)
            outbox.add.assert_called_once()

    def test_disabled_monitor_does_not_scan(self):
        outbox = Mock()
        self.assertEqual(Watcher(outbox).scan({'anpr':{'watch_enabled':False}}), [])
        outbox.add.assert_not_called()
