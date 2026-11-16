"""Run from any directory; prompt for credentials without echo or disk storage."""
import getpass
import os
from pathlib import Path
import sys

root = Path(__file__).resolve().parent.parent
os.chdir(root)
sys.path.insert(0, str(root / 'src'))
from moex_agent.cli import main
from moex_agent.providers import ProviderError

if not os.environ.get('GIGACHAT_AUTH_KEY'):
    os.environ['GIGACHAT_AUTH_KEY'] = getpass.getpass('Authorization Key GigaChat (ввод скрыт): ').strip()
sys.argv = [sys.argv[0], '--config', str(root / 'config/gigachat.json')] + (sys.argv[1:] or ['demo', '--cache-only'])
try:
    main()
except ProviderError as exc:
    print(str(exc), file=sys.stderr)
    sys.exit(2)
finally:
    os.environ.pop('GIGACHAT_AUTH_KEY', None)
