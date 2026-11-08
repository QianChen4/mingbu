"""测试用：每个测试进程用一个临时的软件文件夹，不碰真实数据。必须在导入 app 之前导入本模块。"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
TMP = tempfile.mkdtemp(prefix='mingbu-test-')
os.environ['RENTAL_DATA_DIR'] = os.path.join(TMP, 'data')
os.environ['RENTAL_BACKUP_DIR'] = os.path.join(TMP, 'backups')
os.makedirs(os.environ['RENTAL_DATA_DIR'], exist_ok=True)
