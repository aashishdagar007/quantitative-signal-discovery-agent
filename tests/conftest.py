import os
import sys

# Add the src directory to the path so the package can be imported
src_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'src')
if src_path not in sys.path:
    sys.path.insert(0, src_path)

# Add the .venv site-packages to the path
venv_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), '.venv', 'lib', 'site-packages')
if venv_path not in sys.path:
    sys.path.insert(0, venv_path)
