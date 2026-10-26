import bottle
import os
import socket
import threading

def find_available_port(preferred_port=5234):
    """Finds an open port starting from preferred_port or dynamic."""
    for port in range(preferred_port, preferred_port + 20):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.bind(('127.0.0.1', port))
            s.close()
            return port
        except OSError:
            continue
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()
    return port

class StreamServer:
    def __init__(self, camera_service, port=None, static_dir=None):
        self.camera_service = camera_service
        self.port = port or find_available_port()
        self.static_dir = static_dir
        self.app = bottle.Bottle()
        self._setup_routes()
        self.thread = None

    def _setup_routes(self):
        @self.app.hook('after_request')
        def enable_cors():
            bottle.response.headers['Access-Control-Allow-Origin'] = '*'
            bottle.response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
            bottle.response.headers['Access-Control-Allow-Headers'] = 'Origin, Accept, Content-Type, X-Requested-With'

        @self.app.route('/video_feed')
        def video_feed():
            return bottle.Response(
                self.camera_service.generate_mjpeg(),
                headers={
                    'Content-Type': 'multipart/x-mixed-replace; boundary=frame',
                    'Cache-Control': 'no-cache, private, no-store, must-revalidate, max-age=0, post-check=0, pre-check=0',
                    'Pragma': 'no-cache',
                    'Expires': '0'
                }
            )

        @self.app.route('/snapshot.jpg')
        @self.app.route('/frame')
        def snapshot():
            jpeg = self.camera_service.get_jpeg()
            return bottle.HTTPResponse(
                [jpeg],
                headers={
                    'Content-Type': 'image/jpeg',
                    'Content-Length': str(len(jpeg)),
                    'Cache-Control': 'no-cache, no-store, must-revalidate, max-age=0',
                    'Pragma': 'no-cache',
                    'Expires': '0'
                }
            )



        @self.app.route('/status')
        def status():
            return self.camera_service.get_status()

        # Serve static frontend dist if configured
        if self.static_dir and os.path.isdir(self.static_dir):
            @self.app.route('/')
            @self.app.route('/<filepath:path>')
            def serve_static(filepath='index.html'):
                if not filepath or filepath == '/':
                    filepath = 'index.html'
                return bottle.static_file(filepath, root=self.static_dir)

    def start(self):
        import time

        def run():
            bottle.run(self.app, host='127.0.0.1', port=self.port, quiet=True)

        self.thread = threading.Thread(target=run, daemon=True)
        self.thread.start()

        # Wait until local server is actively accepting connections
        for _ in range(40):
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(0.05)
                s.connect(('127.0.0.1', self.port))
                s.close()
                break
            except Exception:
                time.sleep(0.05)

        return self.port

