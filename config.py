import os

PRINTER_NAME = "XP360B"
HOST = "0.0.0.0"
PORT = 8080
API_KEY = "agustinmanya1994"

# Label dimensions: 80x100mm at 203 DPI
LABEL_WIDTH_PX = 639   # 80mm * 203 / 25.4
LABEL_HEIGHT_PX = 799  # 100mm * 203 / 25.4
LABEL_MEDIA = "Custom.80x100mm"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INDEX_FILE = os.path.join(BASE_DIR, "index.html")

MAX_LOG_TEXT_BODY = 4000
MAX_LOG_BINARY_PREVIEW = 64
