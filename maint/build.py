#!/usr/bin/env python



import os
import shutil
from subprocess import check_call
import shlex

try:
    shutil.rmtree('build')
    os.mkdir('build')
except OSError:
    pass

build_cmd = "conda build conda.recipe --output-folder build/"
print(build_cmd)
check_call(shlex.split(build_cmd))
