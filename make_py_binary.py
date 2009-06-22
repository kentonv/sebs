#! /usr/bin/python
# Scalable Extendable Build System
# Copyright (c) 2009 Kenton Varda.  All rights reserved.
# http://code.google.com/p/sebs
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are
# met:
#
#     * Redistributions of source code must retain the above copyright
# notice, this list of conditions and the following disclaimer.
#     * Redistributions in binary form must reproduce the above
# copyright notice, this list of conditions and the following disclaimer
# in the documentation and/or other materials provided with the
# distribution.
#     * Neither the name of the SEBS project nor the names of its
# contributors may be used to endorse or promote products derived from
# this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
# "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
# LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
# A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT
# OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
# SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
# LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
# DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY
# THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
# (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
# OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

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
