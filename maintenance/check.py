"""Run a real check; write a receipt only after its command exits successfully."""
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
def main():
    name, *command = sys.argv[1:]
    if command and command[0] == '--': command.pop(0)
    path = ROOT / 'validation-evidence' / (name + '.json')
    path.parent.mkdir(exist_ok=True)
    result_record = dict(status='running', command=command, cwd=str(Path.cwd()))
    path.write_text(json.dumps(result_record, indent=2) + '\n')
    result = subprocess.run(command)
    result_record['status'] = 'passed' if result.returncode == 0 else 'failed'
    path.write_text(json.dumps(result_record, indent=2) + '\n')
    return result.returncode

if __name__ == '__main__': sys.exit(main())
