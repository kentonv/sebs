#! /usr/bin/python
# Scalable Extendable Build System
# Copyright (c) 2009 Kenton Varda and contributors.  All rights reserved.
# Portions copyright Google, Inc.
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
#   configure:  Lock-in a set of environment variables that will be used in
#     subsequent builds.  Should support setting names for different
#     configurations.
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

import cPickle
import getopt
import os
import shutil
import sys
import threading

from sebs.builder import Builder
from sebs.core import Rule, Test
from sebs.filesystem import DiskDirectory, VirtualDirectory, MappedDirectory
from sebs.helpers import typecheck
from sebs.loader import Loader, BuildFile
from sebs.console import make_console, ColoredText
from sebs.runner import SubprocessRunner, CachingRunner

class UsageError(Exception):
  pass

class _WorkingDirMapping(MappedDirectory.Mapping):
  """Sometimes we want to put all build output (including intermediates) in
  a different directory, e.g. when cross-compiling.  We also want to put the
  "mem" subdirectory into a VirtualDirectory.  This class implements a
  mapping which can be used with MappedDirectory to accomplish these things."""

  def __init__(self, source_dir, output_dir, mem_dir):
    super(_WorkingDirMapping, self).__init__()
    self.__source_dir = source_dir
    self.__output_dir = output_dir
    self.__mem_dir = mem_dir

  def map(self, filename):
    # Note:  We intentionally consider any directory name starting with "src"
    #   (including, e.g., "src-unofficial") as a source directory.
    if filename.startswith("src"):
      return (self.__source_dir, filename)
    elif filename.startswith("mem/"):
      return (self.__mem_dir, filename[4:])
    else:
      return (self.__output_dir, filename)

def _args_to_rules(loader, args):
  """Given a list of command-line arguments like 'foo/bar.sebs:baz', return an
  iterator of rules which should be built."""

  typecheck(args, list, basestring)

  for arg in args:
    if arg.startswith("src/") or arg.startswith("src\\"):
      # For ease of use, we allow files to start with "src/", so tab completion
      # can be used.
      arg = arg[4:]
    elif arg.startswith("//"):
      # We also allow files to start with "//" which mimics to the syntax given
      # to sebs.import_.
      arg = arg[2:]
    target = loader.load(arg)

    if isinstance(target, BuildFile):
      for name, value in target.__dict__.items():
        if isinstance(value, Rule):
          yield value
    elif not isinstance(target, Rule):
      raise UsageError("%s: Does not name a rule." % arg)
    else:
      yield target

def build(root_dir, argv):
  try:
    opts, args = getopt.getopt(argv[1:], "vj:", [])
  except getopt.error, message:
    raise UsageError(message)

  runner = None
  caching_runner = None
  verbose = False
  console = make_console(sys.stdout)
  threads = 1

  for name, value in opts:
    if name == "-v":
      verbose = True
    elif name == "-j":
      threads = int(value)

  if runner is None:
    runner = SubprocessRunner(root_dir, console, verbose)
    caching_runner = CachingRunner(runner, root_dir, console)
    runner = caching_runner

    if os.path.exists("cache.pickle"):
      db = open("cache.pickle", "rb")
      caching_runner.restore_cache(cPickle.load(db))
      db.close()

  loader = Loader(root_dir)
  builder = Builder(root_dir, console)

  if argv[0] == "test":
    for rule in list(_args_to_rules(loader, args)):
      if isinstance(rule, Test):
        builder.add_test(rule)
  else:
    for rule in list(_args_to_rules(loader, args)):
      builder.add_rule(rule)

  thread_objects = []
  success = True
  for i in range(0, threads):
    thread_objects.append(
      threading.Thread(target = builder.build, args = [runner]))
    thread_objects[-1].start()
  try:
    for thread in thread_objects:
      thread.join()
  except KeyboardInterrupt:
    if not builder.failed:
      console.write(ColoredText(ColoredText.RED, "INTERRUPTED"))
      builder.failed = True
    for thread in thread_objects:
      thread.join()
  finally:
    db = open("cache.pickle", "wb")
    cPickle.dump(caching_runner.save_cache(), db, cPickle.HIGHEST_PROTOCOL)
    db.close()

  if builder.failed:
    return 1

  if argv[0] == "test":
    if not builder.print_test_results():
      return 1

  return 0

def clean(root_dir, argv):
  if len(argv) > 1:
    raise UsageError("clean currently accepts no arguments.")

  print "Deleting all output directories..."
  for dir in ["tmp", "bin", "lib", "share"]:
    if root_dir.exists(dir):
      shutil.rmtree(root_dir.get_disk_path(dir))

  for file in [ "mem.pickle", "cache.pickle" ]:
    if os.path.exists(file):
      os.remove(file)

def main(argv):
  try:
    opts, args = getopt.getopt(argv[1:], "h", ["help", "output="])
  except getopt.error, message:
    raise UsageError(message)

  source_dir = DiskDirectory(".")
  output_dir = source_dir
  mem_dir = VirtualDirectory()

  for name, value in opts:
    if name in ("-h", "--help"):
      print __doc__
      return 0
    elif name == "--output":
      output_dir = DiskDirectory(value)

  root_dir = MappedDirectory(
      _WorkingDirMapping(source_dir, output_dir, mem_dir))

  if len(args) == 0:
    raise UsageError("Missing command.")

  if os.path.exists("mem.pickle"):
    db = open("mem.pickle", "rb")
    mem_dir.restore(cPickle.load(db))
    db.close()

  save_mem = True

  try:
    if args[0] in ("build", "test"):
      return build(root_dir, args)
    elif args[0] == "clean":
      save_mem = False
      return clean(root_dir, args)
    else:
      raise UsageError("Unknown command: %s" % args[0])
  finally:
    if save_mem:
      db = open("mem.pickle", "wb")
      cPickle.dump(mem_dir.save(), db, cPickle.HIGHEST_PROTOCOL)
      db.close()
    else:
      if os.path.exists("mem.pickle"):
        os.remove("mem.pickle")

if __name__ == "__main__":
  try:
    sys.exit(main(sys.argv))
  except UsageError, error:
    print >>sys.stderr, error.message
    print >>sys.stderr, "for help use --help"
    sys.exit(2)
