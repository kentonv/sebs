#! /usr/bin/python
# Scalable Extensible Build System
# Copyright (c) 2009 Kenton Varda.  All rights reserved.

"""Constructs a par file from a set of Python sources."""

import os
import stat
import sys
import tempfile
import zipfile

temporary = tempfile.NamedTemporaryFile()
tempname = temporary.name
temporary.close()

zip = zipfile.ZipFile(tempname, "w")

for file in sys.argv[3:]:
  if file.startswith("src/") or file.startswith("tmp/"):
    arcname = file[4:]
  else:
    arcname = file
  zip.write(file, arcname)

zip.close()

fd = os.open(sys.argv[2], os.O_WRONLY | os.O_TRUNC | os.O_CREAT, 0777)
file = os.fdopen(fd, "w")

file.write(
"""#! /bin/sh
PYTHONPATH=`which $0`:"$PYTHONPATH" python -m %s "$@" || exit 1
exit 0
""" % sys.argv[1])

temporary = open(tempname, "rb")
file.write(temporary.read())
temporary.close()
os.remove(tempname)

file.close()
