#! /usr/bin/python
# Scalable Extensible Build System
# Copyright (c) 2009 Kenton Varda.  All rights reserved.

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
from sebs.core import Rule
from sebs.filesystem import DiskDirectory
from sebs.helpers import typecheck
from sebs.loader import Loader

class UsageError(Exception):
  pass

def _args_to_rules(loader, args):
  """Given a list of command-line arguments like 'foo/bar.sebs:baz', return an
  iterator of rules which should be built."""
  
  typecheck(args, list, basestring)
  
  for arg in args:
    parts = arg.split(":")
    if len(parts) > 2:
      raise UsageError("Invalid rule identifier: %s" % arg)
    
    filename = parts[0]
    filename = filename.replace("\\", "/")
    if filename.startswith("src/"):
      filename = filename[4:]
    file = loader.load(filename)
    
    if len(parts) == 1:
      for name in file.__dict__:
        value = file.__dict__[name]
        if isinstance(value, Rule):
          yield value
    else:
      try:
        rule = eval(parts[1], file.__dict__.copy())
      except Exception, e:
        raise UsageError("%s: %s" % (arg, e.message))
      
      if not isinstance(rule, Rule):
        raise UsageError("%s: '%s' does not name a rule." % (arg, parts[1]))
      yield rule

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
  for rule in list(_args_to_rules(loader, args)):
    builder.add_rule(rule)
  
  builder.build(runner)

  return 0

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
  
  if args[0] == "build":
    return build(args)
  else:
    raise UsageError("Currently the only recognized command is 'build'.")

if __name__ == "__main__":
  try:
    sys.exit(main(sys.argv))
  except UsageError, error:
    print >>sys.stderr, error.message
    print >>sys.stderr, "for help use --help"
    sys.exit(2)
