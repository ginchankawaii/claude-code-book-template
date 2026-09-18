import sys
from pathlib import Path

# make `import app...` work when running pytest from the fxsim/ directory
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
