# SPDX-License-Identifier: MIT
import subprocess
import sys
from .cli import main

try:
    main()
except subprocess.CalledProcessError as error:
    print('ant-purifier: native legacy command failed with exit code '+str(error.returncode), file=sys.stderr)
    sys.exit(error.returncode or 1)
except (ValueError, OSError, KeyError) as error:
    print('ant-purifier: '+str(error), file=sys.stderr)
    sys.exit(1)
