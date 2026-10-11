import sys, site
from pathlib import Path
root=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(root),str(root/'.runtime/python')]
site.addsitedir(str(root/'.runtime/python'))
