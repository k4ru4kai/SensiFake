"""Compatibility entry point; implementation lives in legacy/annotation_app.py."""
import sys
from legacy import annotation_app as implementation

if __name__ == "__main__":
    implementation.main()
else:
    sys.modules[__name__] = implementation
