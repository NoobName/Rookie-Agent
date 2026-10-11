import sys,site,os
from pathlib import Path
root=Path(__file__).resolve().parents[1]
site.addsitedir(str(root/'.runtime/python'))
sys.path.insert(0,str(root/'.runtime/python'))
os.environ['PYTHONPATH']=str(root/'.runtime/python')+os.pathsep+str(root)
sys.path.insert(0,str(root))
import PyInstaller.__main__
PyInstaller.__main__.run([
 str(root/'scripts/run_backend.py'),'--name','local-agent-backend','--onedir','--noconfirm',
 '--distpath',str(root/'dist/backend-build'),'--workpath',str(root/'.runtime/pyinstaller'),
 '--specpath',str(root/'.runtime'),'--paths',str(root),'--paths',str(root/'.runtime/python'),
 '--add-data',str(root/'services/agent/migration.sql')+';services/agent',
 '--add-data',str(root/'examples/skills')+';examples/skills',
 '--collect-all','uvicorn','--collect-all','keyring','--collect-all','mcp',
 '--collect-all','docx','--collect-all','openpyxl','--collect-all','pypdf',
 '--collect-all','reportlab','--collect-all','playwright','--collect-all','tzdata',
 '--hidden-import','pywinauto','--hidden-import','win32timezone',
])
