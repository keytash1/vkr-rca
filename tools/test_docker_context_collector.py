import json
import tempfile
import unittest
from pathlib import Path
from docker_context_collector import Collector
from loki_context_probe import LokiContextSource, ContextError
from test_loki_context_probe import CONFIG, LEFT, RIGHT, Opener, payload


class HistoryTests(unittest.TestCase):
    def test_lookback_is_bounded_separate_from_diagnostic_interval(self):
        opener = Opener(payload({'event.name': 'deployment'}, (LEFT-20)*10**9))
        source = LokiContextSource(CONFIG | {'lookback_seconds': 60}, opener=opener)
        result = source.collect('payment', LEFT, RIGHT)
        self.assertEqual(result['start_unix'], LEFT)
        self.assertEqual(result['query_start_unix'], LEFT-60)
        self.assertEqual(result['records'][0]['period'], 'BEFORE_INCIDENT')
        for bad in (-1, 601, True, 1.5):
            with self.assertRaises(ContextError): LokiContextSource(CONFIG | {'lookback_seconds': bad})

    def test_runtime_fields_are_fixed_and_137_does_not_invent_oom(self):
        fields = {'event.name':'exit', 'container.exit_code':137, 'container.id':'a'*64,
                  'event.time_unix_ns':str(LEFT*10**9), 'event.origin':'docker.events',
                  'observer.time_unix_ns':str((LEFT+1)*10**9), 'Config.Env':'SECRET'}
        result = LokiContextSource(CONFIG, opener=Opener(payload(fields))).collect('payment',LEFT,RIGHT)
        record = result['records'][0]
        self.assertEqual(record['timestamp_semantics'], 'SOURCE_REPORTED_EVENT_TIME')
        self.assertNotIn('SECRET', json.dumps(record))
        self.assertEqual(record['fields']['event.name'], 'exit')
        self.assertNotIn('oom', json.dumps(record))

    def test_durable_replay_scope_changes_and_same_exit_code(self):
        config = {'docker_host':'unix:///unused', 'project':'teaching', 'context':CONFIG}
        image = 'sha256:'+'b'*64
        memory = [32*1024**2]
        reader = lambda *args: json.dumps({'image':image, 'memory':memory[0]})
        def event(action, stamp, instance='a'*64, service='payment-v1'):
            return {'Type':'container','Action':action,'timeNano':stamp,'Actor':{'ID':instance,
                'Attributes':{'com.docker.compose.project':'teaching', 'com.docker.compose.service':service,'exitCode':'137'}}}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'outbox.sqlite'
            collector = Collector(config, path, reader=reader)
            events = [event('start',10**9), event('oom',2*10**9), event('die',3*10**9), event('die',4*10**9,service='unrelated')]
            self.assertEqual(collector.capture(events,5*10**9),3)
            self.assertEqual(collector.capture(events,5*10**9),0)
            collector.db.close()
            collector = Collector(config, path, reader=reader)
            memory[0] *= 2
            self.assertEqual(collector.capture([event('start',6*10**9,instance='c'*64)],7*10**9),2)
            fields = [json.loads(r[0]) for r in collector.db.execute('SELECT line FROM outbox')]
            self.assertEqual(sum(f['event.name']=='oom' for f in fields),1)
            self.assertEqual(sum(f['event.name']=='configuration_change' for f in fields),1)
            self.assertTrue(all('Config.Env' not in f for f in fields))
            self.assertEqual(collector.capture([event('start',8*10**9,instance='d'*64)],30*10**9),1)
            collector.db.close()


if __name__ == '__main__': unittest.main()
