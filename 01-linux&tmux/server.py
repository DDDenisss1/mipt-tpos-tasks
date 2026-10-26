import http.server
import socketserver
import argparse
import time
class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/healthcheck':
            self.send_response(200)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            self.wfile.write(b"OK")
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {args[0]}", flush=True)

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, required=True)
    args = parser.parse_args()

    print(f"Starting server on port {args.port}", flush=True)
    try:
        with socketserver.TCPServer(("", args.port), Handler) as httpd:
            httpd.serve_forever()
    except Exception as e:
        print(f"Server crashed: {e}", flush=True)
