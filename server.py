from http.server import HTTPServer

from config import HOST, PORT
from handlers import PrintHandler

if __name__ == "__main__":
    server = HTTPServer((HOST, PORT), PrintHandler)
    print(f"Print API listening on http://{HOST}:{PORT}", flush=True)
    server.serve_forever()
