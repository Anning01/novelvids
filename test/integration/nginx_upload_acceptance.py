"""Exercise the shipped proxy with isolated containers and generated, non-user data."""
import argparse
import http.client
import json
import subprocess
import time
from uuid import uuid4

RECEIVER = '''from http.server import BaseHTTPRequestHandler, HTTPServer
import json
class Handler(BaseHTTPRequestHandler):
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
HTTPServer(('0.0.0.0', 8000), Handler).serve_forever()
'''


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
