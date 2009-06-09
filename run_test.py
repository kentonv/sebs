#! /usr/bin/python
# Scalable Extensible Build System
# Copyright (c) 2009 Kenton Varda.  All rights reserved.

"""Executes a command, saving its output to a file, and then prints a PASS or
FAIL message based on the exit code.  This is useful for running tests from
within a SEBS build."""

import subprocess
import sys

test_name = sys.argv[2]
output_name = sys.argv[1]
output = open(output_name, "wb")

proc = subprocess.Popen(sys.argv[3:], stdout = output, stderr = output)
if proc.wait() == 0:
  print "\033[1;32mPASS:\033[1;m", test_name
else:
  print "\033[1;31mFAIL:\033[1;m", test_name
  print " ", output_name
