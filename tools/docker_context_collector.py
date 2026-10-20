"""Optional operator-side Docker events -> durable SQLite outbox -> Loki.

Never run inside RCA or give its daemon credentials to RCA/LLM. The daemon
account remains privileged even though this tool only invokes read operations.
Collection starts at installation; Docker's short event backlog is NOT a
complete audit history. Observed changes cover image IDs and memory limits only.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import time
from urllib.request import Request

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'cmd/thesis_demo'))
from context_source import LokiContextSource, NoRedirect, build_opener

IDENT = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,95}\Z')
EVENTS = {'oom': 'oom', 'die': 'exit', 'start': 'start', 'restart': 'restart'}


def docker(host, *args):
    result = subprocess.run(['docker', '--host', host, *args], capture_output=True, timeout=20)
    if result.returncode or len(result.stdout) > 1024 * 1024:
        raise RuntimeError('DOCKER_READ_FAILED')  # Never print daemon stderr/credentials.
    return result.stdout.decode('utf-8')


class Collector:
    def __init__(self, config, database, *, reader=docker):
        if set(config) != {'docker_host', 'project', 'context'} or not isinstance(config['docker_host'], str):
            raise ValueError('INVALID_COLLECTOR_CONFIG')
        self.source = LokiContextSource(config['context'])
        if not IDENT.fullmatch(config['project']) or not config['context']['labels']:
            raise ValueError('EXPLICIT_PROJECT_AND_LOKI_SCOPE_REQUIRED')
        if len(set(self.source.services.values())) != len(self.source.services):
            raise ValueError('AMBIGUOUS_SERVICE_MAPPING')
        self.config, self.reader = config, reader
        self.services = set(self.source.services.values())
        self.db = sqlite3.connect(database)
        self.db.executescript('''
          CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS state(instance TEXT PRIMARY KEY, service TEXT NOT NULL, image TEXT, memory INTEGER, stopped INTEGER NOT NULL);
          CREATE TABLE IF NOT EXISTS outbox(id TEXT PRIMARY KEY, stamp TEXT NOT NULL, service TEXT NOT NULL,
            line TEXT NOT NULL, delivered INTEGER NOT NULL DEFAULT 0);
        ''')
        binding = hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()
        existing = self.db.execute("SELECT value FROM meta WHERE key='binding'").fetchone()
        if existing and existing[0] != binding:
            raise ValueError('DATABASE_BOUND_TO_DIFFERENT_SCOPE')
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO meta VALUES('binding',?)", (binding,))

    def capture(self, events, observed_ns):
        """Persist a batch atomically. Replayed daemon entries are idempotent."""
        count = 0
        with self.db:
            for event in events:
                actor = event.get('Actor', {})
                labels = actor.get('Attributes', {})
                service, instance = labels.get('com.docker.compose.service'), actor.get('ID')
                if (event.get('Type') != 'container' or labels.get('com.docker.compose.project') != self.config['project']
                        or service not in self.services or not isinstance(instance, str)
                        or not re.fullmatch('[0-9a-f]{64}', instance)):
                    continue
                action, stamp = event.get('Action', ''), event.get('timeNano')
                if type(stamp) is not int or not 0 < stamp <= observed_ns:
                    continue
                kind = EVENTS.get(action, 'health_change' if action.startswith('health_status: ') else None)
                if not kind:
                    continue
                identifier = hashlib.sha256(json.dumps([instance, action, stamp]).encode()).hexdigest()
                if self.db.execute('SELECT 1 FROM outbox WHERE id=?', (identifier,)).fetchone():
                    continue
                fields = {'event.name': kind, 'event.origin': 'docker.events', 'container.id': instance,
                          'event.time_unix_ns': str(stamp), 'observer.time_unix_ns': str(observed_ns)}
                code = labels.get('exitCode', '')
                if isinstance(code, str) and code.isdecimal() and 0 <= int(code) <= 255:
                    fields['container.exit_code'] = int(code)
                changes = []
                if action == 'die':
                    self.db.execute('UPDATE state SET stopped=1 WHERE instance=?', (instance,))
                if action == 'start' and observed_ns - stamp <= 10_000_000_000:
                    # Select two non-secret fields only. No Config.Env, mounts,
                    # labels, command line, image name or full inspect JSON.
                    try:
                        inspected = json.loads(self.reader(self.config['docker_host'], 'inspect', '--format',
                            '{"image":{{json .Image}},"memory":{{json .HostConfig.Memory}}}', instance))
                    except (RuntimeError, ValueError, subprocess.TimeoutExpired):
                        inspected = {}
                    image, memory = inspected.get('image'), inspected.get('memory')
                    if isinstance(image, str) and re.fullmatch('sha256:[0-9a-f]{64}', image) and type(memory) is int and 0 <= memory <= 2**60:
                        fields['container.memory_limit_bytes'] = memory
                        # Only a stopped previous instance of the same service
                        # establishes replacement, not concurrent replicas.
                        previous = self.db.execute('SELECT image,memory FROM state WHERE instance=?', (instance,)).fetchone()
                        if previous is None:
                            predecessors = self.db.execute('SELECT image,memory,stopped FROM state WHERE service=?', (service,)).fetchall()
                            if len(predecessors) == 1 and predecessors[0][2] == 1:
                                previous = predecessors[0][:2]
                        if previous:
                            if image != previous[0]: changes.append('deployment')
                            if memory != previous[1]: changes.append('configuration_change')
                        self.db.execute('INSERT OR REPLACE INTO state VALUES(?,?,?,?,0)', (instance, service, image, memory))
                for suffix, record in [('', fields)] + [(c, fields | {'event.name': c}) for c in changes]:
                    self.db.execute('INSERT OR IGNORE INTO outbox(id,stamp,service,line) VALUES(?,?,?,?)',
                        (identifier + suffix, str(stamp), service, json.dumps(record, sort_keys=True)))
                    count += 1
                if self.db.execute('SELECT count(*) FROM outbox').fetchone()[0] > 10000:
                    raise RuntimeError('LEDGER_LIMIT_ROTATE_DATABASE_EXPLICITLY')
        return count

    def poll(self):
        # Rounded overlap is intentional; stable IDs remove duplicates. A
        # restart/gap may exceed Docker's 256-entry history: coverage UNKNOWN.
        row = self.db.execute("SELECT value FROM meta WHERE key='until'").fetchone()
        until = int(time.time())
        since = int(row[0]) - 1 if row else until - 60
        data = self.reader(self.config['docker_host'], 'events', '--since', str(since), '--until', str(until),
                           '--filter', 'type=container', '--filter', 'label=com.docker.compose.project=' + self.config['project'],
                           '--format', '{{json .}}')
        events = [json.loads(line) for line in data.splitlines() if line]
        count = self.capture(events, time.time_ns())
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO meta VALUES('until',?)", (str(until),))
        return count

    def flush(self):
        rows = self.db.execute('SELECT id,stamp,service,line FROM outbox WHERE delivered=0 ORDER BY length(stamp),stamp,id LIMIT 100').fetchall()
        if not rows: return 0
        token = os.environ.get(self.source.token_env) if self.source.token_env else None
        if self.source.token_env and (not token or '\r' in token or '\n' in token):
            raise RuntimeError('SOURCE_AUTH_UNAVAILABLE')
        headers = {'Content-Type': 'application/json'}
        if token: headers['Authorization'] = 'Bearer ' + token
        streams = [{'stream': self.source.labels | {self.source.label: service}, 'values': [[stamp, line]]}
                   for _, stamp, service, line in rows]
        request = Request(self.source.url + '/loki/api/v1/push', data=json.dumps({'streams': streams}).encode(), headers=headers)
        with build_opener(NoRedirect()).open(request, timeout=5) as response:
            if response.status != 204: raise RuntimeError('LOKI_PUSH_FAILED')
        with self.db:
            self.db.executemany('UPDATE outbox SET delivered=1 WHERE id=?', [(row[0],) for row in rows])
        return len(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True)
    parser.add_argument('--database', required=True, help='Private persistent SQLite file, bound to this configuration')
    parser.add_argument('--watch', action='store_true', help='Poll every 5 seconds; supervise with the operator service manager')
    args = parser.parse_args()
    os.umask(0o077)
    with open(args.config, 'rb') as stream:
        data = stream.read(65537)
    if len(data) > 65536: parser.error('CONFIG_BYTE_LIMIT')
    collector = Collector(json.loads(data), args.database)
    try:
        while True:
            try:
                captured = collector.poll()
                sent = collector.flush()
                print(json.dumps({'captured': captured, 'sent': sent, 'coverage': 'BACKLOG_RETENTION_AND_GAPS_UNKNOWN'}), flush=True)
            except Exception:
                print('COLLECTOR_FAILED_OUTBOX_RETAINED', file=sys.stderr)
                if not args.watch: raise SystemExit(1) from None
            if not args.watch: break
            time.sleep(5)
    finally:
        collector.db.close()


if __name__ == '__main__': main()
