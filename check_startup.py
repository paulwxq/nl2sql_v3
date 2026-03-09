import traceback
import sys

try:
    from src.api.main import app
    print("OK: app imported successfully")
except Exception as e:
    print("IMPORT ERROR:")
    traceback.print_exc()
    sys.exit(1)
