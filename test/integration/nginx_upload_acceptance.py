"""Exercise the shipped proxy with isolated containers and generated, non-user data."""
import argparse
import gzip
import http.client
import json
import re
import subprocess
import time
from uuid import uuid4

RECEIVER = r'''from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Event
import json
release = Event()
class Handler(BaseHTTPRequestHandler):
 def do_GET(self):
  if self.path.endswith('/events'):
   release.clear()
   self.send_response(200)
   self.send_header('Content-Type', 'text/event-stream')
   self.send_header('X-Accel-Buffering', 'no')
   self.end_headers()
   self.wfile.write(b'data: first\n\n')
   self.wfile.flush()
   if release.wait(10):
    self.wfile.write(b'data: second\n\n')
   return
  if self.path.endswith('/release'):
   release.set()
  body = json.dumps({'items': list(range(1000))} if self.path.endswith('/large') else {}).encode()
  self.send_response(200)
  self.send_header('Content-Type', 'application/json')
  self.send_header('Content-Length', str(len(body)))
  self.end_headers()
  self.wfile.write(body)
 def do_POST(self):
  remaining = size = int(self.headers.get('Content-Length', 0))
  while remaining:
   chunk = self.rfile.read(min(remaining, 65536))
   if not chunk: break
   remaining -= len(chunk)
  body = json.dumps({'received': size - remaining}).encode()
  self.send_response(200)
  self.send_header('Content-Type', 'application/json')
  self.send_header('Content-Length', str(len(body)))
  self.end_headers()
  self.wfile.write(body)
 def log_message(self, *args): pass
ThreadingHTTPServer(('0.0.0.0', 8000), Handler).serve_forever()
'''


def fetch(port, path, encoding):
    connection = http.client.HTTPConnection('127.0.0.1', port, timeout=5)
    try:
        connection.request('GET', path, headers={'Accept-Encoding': encoding, 'Via': '1.1 test-edge'})
        response = connection.getresponse()
        assert response.status == 200, (path, response.status)
        return response.headers, response.read()
    finally:
        connection.close()


def check_compression(port):
    _, html = fetch(port, '/index.html', 'identity')
    script = re.search(r'<script[^>]+src="([^"]+)"', html.decode()).group(1)
    styles = re.findall(r'<link[^>]+rel="stylesheet"[^>]+href="([^"]+)"', html.decode())
    stylesheet = max(styles, key=lambda path: len(fetch(port, path, 'identity')[1]))
    for path in ('/index.html', script, stylesheet, '/api/test/large'):
        headers, plain = fetch(port, path, 'identity')
        assert headers.get('Content-Encoding') is None, path
        headers, compressed = fetch(port, path, 'gzip')
        assert headers.get('Content-Encoding') == 'gzip', path
        assert 'accept-encoding' in headers.get('Vary', '').lower(), path
        assert gzip.decompress(compressed) == plain and len(compressed) < len(plain), path
        print(f'{path}: {len(plain)} -> {len(compressed)} bytes')

    for path in ('/api/test/small', '/logo.png'):
        headers, _ = fetch(port, path, 'gzip')
        assert headers.get('Content-Encoding') is None, path

    # The upstream sends the second event only after the client receives the first.
    for path in ('/api/test/events', '/v1/test/events'):
        connection = http.client.HTTPConnection('127.0.0.1', port, timeout=5)
        try:
            connection.request('GET', path, headers={'Accept-Encoding': 'gzip'})
            response = connection.getresponse()
            assert response.status == 200 and response.getheader('Content-Encoding') is None, path
            assert response.readline() == b'data: first\n', path
            fetch(port, '/api/test/release', 'identity')
            assert response.read() == b'\ndata: second\n\n', path
        finally:
            connection.close()


def check(docker, backend_image, frontend_image):
    prefix = 'novelvids-upload-check-' + uuid4().hex[:10]
    network, backend, frontend = prefix + '-net', prefix + '-backend', prefix + '-frontend'
    def run(*args):
        return subprocess.check_output([docker, *args], text=True, stderr=subprocess.STDOUT).strip()
    try:
        run('network', 'create', network)
        run('run', '-d', '--name', backend, '--network', network, '--network-alias', 'backend',
            '--entrypoint', 'python', backend_image, '-u', '-c', RECEIVER)
        run('run', '-d', '--name', frontend, '--network', network, '-p', '127.0.0.1::80', frontend_image)
        port = int(run('port', frontend, '80/tcp').rsplit(':', 1)[1])
        for attempt in range(30):
            try:
                run('exec', frontend, 'nginx', '-t')
                run('exec', frontend, 'wget', '-qO-', '-T', '2', '--post-data=', 'http://127.0.0.1/api/file/upload')
                break
            except subprocess.CalledProcessError:
                if attempt == 29:
                    raise
                time.sleep(.2)
        check_compression(port)
        # The second step submits the parsed manuscript again as a JSON body.
        payload = json.dumps({'content': 'x' * (20 * 1024 * 1024)}).encode()
        connection = http.client.HTTPConnection('127.0.0.1', port, timeout=120)
        connection.request('POST', '/api/novel', body=payload, headers={'Content-Type': 'application/json'})
        response = connection.getresponse()
        assert response.status == 200, response.status
        assert json.loads(response.read())['received'] == len(payload)
        connection.close()
        # Stream over 1 GiB without allocating or storing a 1 GiB fixture.
        size = 1024 * 1024 * 1024 + 1
        connection = http.client.HTTPConnection('127.0.0.1', port, timeout=120)
        connection.putrequest('POST', '/api/file/upload')
        connection.putheader('Content-Length', str(size))
        connection.endheaders()
        chunk = b'x' * (1024 * 1024)
        for _ in range(1024):
            connection.send(chunk)
        connection.send(b'x')
        response = connection.getresponse()
        assert response.status == 200, response.status
        assert json.loads(response.read())['received'] == size
        connection.close()
        print('PASS: 20 MiB manuscript JSON and >1 GiB upload forwarded completely.')
    finally:
        for name in (frontend, backend):
            subprocess.run([docker, 'rm', '-f', name], capture_output=True)
        subprocess.run([docker, 'network', 'rm', network], capture_output=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--docker', default='docker')
    parser.add_argument('--backend-image', default='novelvids-backend:release')
    parser.add_argument('--frontend-image', default='novelvids-frontend:release')
    args = parser.parse_args()
    check(args.docker, args.backend_image, args.frontend_image)
