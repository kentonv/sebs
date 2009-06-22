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

# TODO(kenton):
#
# Commands:
#   build:  Builds targets and dependencies.
#   test:  Builds test rules and executes them.
#   script:  Like build, but generates a script containing the actions instead
#     of actually building.  Scripts may be in multiple formats, including
#     Unix shell, Windows batch file, or configure/Makefile pair.
#   placeholders:  Builds a package then constructs "placeholder" sebs files
#     that work as drop-in replacements except that they assume that everything
#     is already built and installed.  Useful for distributing dependents
#     without the dependencies.
#   dist:  Makes a distribution containing some set of directories.
#     Dependencies not in that set are replaced with placeholders.  Build
#     scripts are optionally included.
#   install:  Installs some targets.  Can recursively install dependencies or
#     assume they are already installed.
#   uninstall:  Reverse of install.
#   clean:  Clean some or all of the output from previous SEBS builds.
#   help:  Display help.
#
# ActionRunner that skips actions when the inputs and commands haven't changed.
#
# Background server that accepts commands and doesn't have to reload sebs files.

import getopt
import sys

from sebs.builder import Builder, DryRunner, SubprocessRunner
from sebs.core import Rule, Test
from sebs.filesystem import DiskDirectory
from sebs.helpers import typecheck
from sebs.loader import Loader, BuildFile

class UsageError(Exception):
  pass

def _args_to_rules(loader, args):
  """Given a list of command-line arguments like 'foo/bar.sebs:baz', return an
  iterator of rules which should be built."""
  
  typecheck(args, list, basestring)
  
  for arg in args:
    if arg.startswith("src/") or arg.startswith("src\\"):
      arg = arg[4:]
    target = loader.load(arg)
    
    if isinstance(target, BuildFile):
      for name, value in target.__dict__.items():
        if isinstance(value, Rule):
          yield value
    elif not isinstance(target, Rule):
      raise UsageError("%s: Does not name a rule." % arg)
    else:
      yield target

def build(argv):
  try:
    opts, args = getopt.getopt(argv[1:], "", ["dry"])
  except getopt.error, message:
    raise UsageError(message)

  runner = SubprocessRunner()
  
  for name, value in opts:
    if name == "--dry":
      runner = DryRunner(sys.stdout)
  
  root_dir = DiskDirectory(".")
  loader = Loader(root_dir)
  builder = Builder(root_dir)
  
  if argv[0] == "test":
    for rule in list(_args_to_rules(loader, args)):
      if isinstance(rule, Test):
        builder.add_test(rule)
    success = builder.test(runner)
  else:
    for rule in list(_args_to_rules(loader, args)):
      builder.add_rule(rule)
    success = builder.build(runner)

  if success:
    return 0
  else:
    return 1

def main(argv):
  try:
    opts, args = getopt.getopt(argv[1:], "h", ["help"])
  except getopt.error, message:
    raise UsageError(message)
  
  for name, value in opts:
    if name in ("-h", "--help"):
      print __doc__
      return 0
  
  if len(args) == 0:
    raise UsageError("Missing command.")
  
  if args[0] in ("build", "test"):
    return build(args)
  else:
    raise UsageError("Unknown command: %s" % args[0])

if __name__ == "__main__":
  try:
    sys.exit(main(sys.argv))
  except UsageError, error:
    print >>sys.stderr, error.message
    print >>sys.stderr, "for help use --help"
    sys.exit(2)
