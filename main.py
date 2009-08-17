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

  def __init__(self, source_dir, output_dir, mem_dir, env_dir, alt_configs):
    super(_WorkingDirMapping, self).__init__()
    self.__source_dir = source_dir
    self.__output_dir = output_dir
    self.__mem_dir = mem_dir
    self.__env_dir = env_dir
    self.__alt_configs = alt_configs

    if env_dir.exists("$config"):
      self.__configured_env = set(env_dir.read("$config").split(","))
    else:
      self.__configured_env = set()

  def map(self, filename):
    # Note:  We intentionally consider any directory name starting with "src"
    #   (including, e.g., "src-unofficial") as a source directory.
    if filename.startswith("src"):
      return (self.__source_dir, filename)
    elif filename.startswith("mem/"):
      return (self.__mem_dir, filename[4:])
    elif filename.startswith("env/"):
      env_name = filename[4:]
      self.__update_env(env_name)
      return (self.__env_dir, env_name)
    elif filename.startswith("alt/"):
      parts = filename[4:].split("/", 1)
      config = self.__alt_configs.get(parts[0])
      if len(parts) > 1 and config is not None:
        return (config.root_dir, parts[1])
      else:
        return (self.__output_dir, filename)
    else:
      return (self.__output_dir, filename)

  def __update_env(self, filename):
    """Every time an environment variable is accessed we check to see if it has
    changed."""

    if filename.startswith("set/"):
      env_name = filename[4:]
    else:
      env_name = filename

    # We only update from the environment for variables that were not explicitly
    # configured.
    if env_name not in self.__configured_env:
      if filename.startswith("set/"):
        if env_name in os.environ:
          value = "true"
        else:
          value = "false"
      else:
        value = os.environ.get(env_name, "")

      if not self.__env_dir.exists(filename) or \
         self.__env_dir.read(filename) != value:
        # Value has changed.  Update.
        self.__env_dir.write(filename, value)

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

def _restore_pickle(obj, dir, filename):
  if dir is not None:
    filename = dir.get_disk_path(filename)
  if os.path.exists(filename):
    db = open(filename, "rb")
    obj.restore(cPickle.load(db))
    db.close()

def _save_pickle(obj, dir, filename):
  if dir is not None:
    filename = dir.get_disk_path(filename)
  db = open(filename, "wb")
  cPickle.dump(obj.save(), db, cPickle.HIGHEST_PROTOCOL)
  db.close()

class _Configuration(object):
  def __init__(self, output_path, all_configs = None):
    # We want to make sure to construct only one copy of each config, even
    # if configs refer to each other or multiple configs refer to a shared
    # config.  So, all_configs maps names to configs that we have already
    # constructed.
    if all_configs is None:
      # Note that if we just make all_configs default to {} in the method
      # signature, then Python will create a single empty map to use as the
      # default value for all calls rather than create a new one every call.
      # Since we modify all_configs during this method, we would be modifying
      # the shared default value, which would be bad.  If you don't understand
      # what I mean, try typing the following into the interpreter and then
      # calling it several times with no argument:
      #   def f(l = []):
      #     l.append("foo")
      #     return l
      # Ouchies.
      all_configs = {}
    if output_path is None:
      all_configs[""] = self
    else:
      all_configs[output_path] = self

    self.name = output_path
    self.source_dir = DiskDirectory(".")
    if output_path is None:
      self.output_dir = self.source_dir
    else:
      self.source_dir.mkdir(output_path)
      self.output_dir = DiskDirectory(output_path)
    self.mem_dir = VirtualDirectory()
    self.env_dir = VirtualDirectory()
    _restore_pickle(self.mem_dir, self.output_dir, "mem.pickle")
    _restore_pickle(self.env_dir, self.output_dir, "env.pickle")
    self.alt_configs = {}
    self.mapping = _WorkingDirMapping(self.source_dir, self.output_dir,
                                      self.mem_dir, self.env_dir,
                                      self.alt_configs)
    self.root_dir = MappedDirectory(self.mapping)

    self.alt_configs["host"] = self

    if self.env_dir.exists("$mappings"):
      mappings = self.env_dir.read("$mappings").split(":")
      for mapping in mappings:
        if mapping == "":
          continue
        alias, name = mapping.split("=", 1)
        if name in all_configs:
          self.alt_configs[alias] = all_configs[name]
        else:
          if name == "":
            name = None
          self.alt_configs[alias] = _Configuration(name, all_configs)

  def save(self):
    _save_pickle(self.mem_dir, self.root_dir, "mem.pickle")
    _save_pickle(self.env_dir, self.root_dir, "env.pickle")

  def getenv(self, name):
    if self.root_dir.read("env/set/" + name) == "true":
      return self.root_dir.read("env/" + name)
    else:
      return None

  def get_all_linked_configs(self):
    result = set()
    self.__get_all_linked_configs_recursive(result)
    return result

  def __get_all_linked_configs_recursive(self, result):
    if self in result:
      return

    result.add(self)
    for link in self.alt_configs.values():
      link.__get_all_linked_configs_recursive(result)

# ====================================================================

def configure(config, argv):
  try:
    opts, args = getopt.getopt(argv[1:], "C:o", [])
  except getopt.error, message:
    raise UsageError(message)

  output = False
  mappings = {}
  for name, value in opts:
    if name == "-C":
      parts = value.split("=", 1)
      if len(parts) == 1:
        mappings[parts[0]] = parts[0]
      else:
        mappings[parts[0]] = parts[1]
    elif name == "-o":
      output = True

  if output:
    if config.env_dir.exists("$mappings"):
      mappings = config.env_dir.read("$mappings").split(":")
      for mapping in mappings:
        if mapping == "":
          continue
        print "-C" + mapping

    if config.env_dir.exists("$config"):
      locked_vars = config.env_dir.read("$config").split(",")
    else:
      locked_vars = []

    for var in locked_vars:
      if var == "":
        pass
      elif config.env_dir.read("set/" + var) == "true":
        print "%s=%s" % (var, config.env_dir.read(var))
      else:
        print var + "-"

  else:
    locked_vars = []

    for arg in args:
      parts = arg.split("=", 1)
      name = parts[0]

      unset = len(parts) == 1 and name.endswith("-")
      if unset:
        name = name[:-1]

      if not name.replace("_", "").isalnum():
        raise UsageError("%s: Invalid environment variable name." % name)

      if len(parts) == 2:
        value = parts[1]
        is_set = "true"
      elif name in os.environ and not unset:
        value = os.environ[name]
        is_set = "true"
      else:
        value = ""
        is_set = "false"
      config.env_dir.write(name, value)
      config.env_dir.write("set/" + name, is_set)

      locked_vars.append(name)

    config.env_dir.write("$config", ",".join(locked_vars))

    config.env_dir.write("$mappings",
        ":".join(["=".join(mapping) for mapping in mappings.items()]))

# --------------------------------------------------------------------

def build(config, argv):
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
    runner = SubprocessRunner(console, verbose)
    caching_runner = CachingRunner(runner, console)
    runner = caching_runner

    # Note that all configurations share a common cache.pickle.
    _restore_pickle(caching_runner, None, "cache.pickle")

  loader = Loader(config.root_dir)
  builder = Builder(console)

  if argv[0] == "test":
    for rule in list(_args_to_rules(loader, args)):
      if isinstance(rule, Test):
        builder.add_test(config, rule)
  else:
    for rule in list(_args_to_rules(loader, args)):
      builder.add_rule(config, rule)

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
    _save_pickle(caching_runner, None, "cache.pickle")

  if builder.failed:
    return 1

  if argv[0] == "test":
    if not builder.print_test_results():
      return 1

  return 0

# --------------------------------------------------------------------

def clean(config, argv):
  try:
    opts, args = getopt.getopt(argv[1:], "", ["expunge"])
  except getopt.error, message:
    raise UsageError(message)

  expunge = False

  for name, value in opts:
    if name == "--expunge":
      expunge = True

  # All configurations share one cache.  It's *probably* harmless to leave it
  # untouched, but then again if the implementation was perfect then "clean"
  # would never be necessary.  So we nuke it.
  # TODO(kenton):  We could load the cache and remove only the entries that
  #   are specific to the configs being cleaned.
  if os.path.exists("cache.pickle"):
    os.remove("cache.pickle")

  for linked_config in config.get_all_linked_configs():
    if linked_config.name is None:
      print "Cleaning default config."
    else:
      print "Cleaning:", linked_config.name

    for dir in ["tmp", "bin", "lib", "share", "mem", "env"]:
      if linked_config.root_dir.exists(dir):
        shutil.rmtree(linked_config.root_dir.get_disk_path(dir))

    for file in [ "mem.pickle", "env.pickle" ]:
      if linked_config.root_dir.exists(file):
        os.remove(linked_config.root_dir.get_disk_path(file))

    if expunge:
      # Try to remove the output directory itself -- will fail if not empty.
      outdir = linked_config.root_dir.get_disk_path(".")
      if outdir.endswith("/."):
        # rmdir doesn't like a trailing "/.".
        outdir = outdir[:-2]
      try:
        os.rmdir(outdir)
      except os.error:
        pass

    else:
      # Restore the parts of env.pickle that were set explicitly.
      new_env_dir = VirtualDirectory()

      if linked_config.env_dir.exists("$mappings"):
        new_env_dir.write("$mappings", linked_config.env_dir.read("$mappings"))
      if linked_config.env_dir.exists("$config"):
        locked_vars = linked_config.env_dir.read("$config")
        new_env_dir.write("$config", locked_vars)

        for var in locked_vars.split(","):
          if var != "":
            new_env_dir.write(var, linked_config.env_dir.read(var))
            new_env_dir.write("set/" + var,
              linked_config.env_dir.read("set/" + var))

        _save_pickle(new_env_dir, linked_config.root_dir, "env.pickle")

# ====================================================================

def main(argv):
  try:
    opts, args = getopt.getopt(argv[1:], "hc:", ["help", "config="])
  except getopt.error, message:
    raise UsageError(message)

  output_path = None

  for name, value in opts:
    if name in ("-h", "--help"):
      print __doc__
      return 0
    elif name in ("-c", "--config"):
      output_path = value

  config = _Configuration(output_path)

  if len(args) == 0:
    raise UsageError("Missing command.")

  should_save = True

  try:
    if args[0] in ("build", "test"):
      return build(config, args)
    elif args[0] == "configure":
      return configure(config, args)
    elif args[0] == "clean":
      should_save = False
      return clean(config, args)
    else:
      raise UsageError("Unknown command: %s" % args[0])
  finally:
    if should_save:
      for linked_config in config.get_all_linked_configs():
        linked_config.save()

if __name__ == "__main__":
  try:
    sys.exit(main(sys.argv))
  except UsageError, error:
    print >>sys.stderr, error.message
    print >>sys.stderr, "for help use --help"
    sys.exit(2)
