import os
import sys


def test_debug_env():
    print("\nPYTHONPATH:", os.environ.get("PYTHONPATH"))
    print("sys.path:")
    for p in sys.path:
        print(p)

    try:
        import pyytdata

        print(f"Successfully imported pyytdata from {pyytdata.__file__}")
    except ImportError as e:
        print(f"Failed to import pyytdata: {e}")
        raise
