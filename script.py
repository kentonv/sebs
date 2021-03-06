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

import os
import pipes

from sebs.command import Command, ScriptWriter
from sebs.core import Action, Artifact, Rule, Test
from sebs.helpers import typecheck

_SCRIPT_INTRO = """
#! /bin/sh
#
# Generated by SEBS.  DO NOT EDIT!
#
# This script is generated by SEBS (the Scalable Extendable Build System) to
# allow this package to be built when SEBS is unavailable.  If you intend to
# do any serious development work on the package, it is recommended that you
# install SEBS and use it rather than rely on this file.

set -euo pipefail

do_clean=no
do_build=no
do_test=no
do_install=no

prefix=

function usage() {
  cat << __END__
Usage:
  $1 [COMMANDS]
__END__
}

function die() {
  echo "$@" >&2
  exit 1
}

function eval_assignment() {
  local varname=$(expr "$1" : '\([^=]*\)=.*')
  local value=$(expr "$1" : '[^=]*=\(.*\)')
  expr "$varname" : '.*[^a-zA-Z0-9_]' > /dev/null &&
      die "Bad variable name: $varname"
  eval $varname=\$value
}

script_name=$(basename $0 .sh)

while test $# -gt 0; do
  case $1 in
    clean )
      do_clean=yes
      do_build=no
      ;;
    build )
      do_build=yes
      ;;
    test )
      do_build=yes
      do_test=yes
      ;;
    install )
      do_build=yes
      do_install=yes
      ;;
    help | --help | -h )
      usage $0
      exit 0
      ;;
    -*=* )  # Don't let --foo=bar be interpreted as an assignment.
      usage $0 >&2
      exit 1
      ;;
    *=* )
      eval_assignment "$1"
      ;;
    * )
      usage $0 >&2
      exit 1
      ;;
  esac
  shift
done

# We always build unless "clean" was specified.
if test $do_clean = no; then
  do_build=yes
fi

# Clean before we do anything else.
if test $do_clean = yes; then
  rm -rf $script_name.cache tmp bin lib share include
fi

# Read the cache, if present.
function read_cache() {
  while read LINE; do
    if test -n "$LINE"; then
      eval_assignment "$LINE"
    fi
  done
}

function write_to_cache() {
  eval "echo $1=\$$1 >> $script_name.cache"
}

if test $do_clean = no; then
  if test -e $script_name.cache; then
    read_cache < $script_name.cache
  fi
else
  # Delete the cache.
  rm -f $script_name.cache
fi

"""

_BUILD_PHASE = 0
_TEST_PHASE = 1
_NO_PHASE = 2

_PHASE_NAMES = ["build", "test"]

def _canonicalize_artifact(artifact):
  while artifact.alt_artifact is not None:
    if artifact.alt_config != "host":
      raise NotImplementedError(
          "Building artifacts under alternate configs in scripts.")
    artifact = artifact.alt_artifact
  return artifact

class _ScriptActionState(object):
  def __init__(self, action):
    self.action = action

    # Set of conditions under which we need to run this action.  Each item in
    # this set is a condition object.
#    self.conditions = set()

    # Commands making up this action.
    self.commands = []

    # Set of artifacts which must be built before running this action, including
    # those which are only conditionally needed.
    self.inputs = set()
    self.input_names = set()

    # Set of artifacts which are built by this action.
    self.outputs = set()
    self.output_names = set()
    self.output_vars = set()

    self.status_expression = None

    self.phase = _NO_PHASE

class _ScriptStateMap(object):
  def __init__(self):
    self.__actions = {}

    # Maps actions to variable names.
    self.__mem_vars = {}

  def action_state(self, action):
    typecheck(action, Action)

    result = self.__actions.get((action))
    if result is None:
      result = _ScriptActionState(action)
      action.command.write_script(_ScriptWriterImpl(result, self))
      self.__actions[(action)] = result
    return result

  def varname(self, artifact):
    result = self.__mem_vars.get(artifact)
    if result is None:
      count = len(self.__mem_vars)
      name = os.path.basename(artifact.filename)
      result = "mem_%d_%s" % (count, name)
      self.__mem_vars[artifact] = result
    return result

class _ScriptWriterImpl(ScriptWriter):
  def __init__(self, action_state, state_map):
    self.__action_state = action_state
    self.__state_map = state_map

  def add_command(self, text):
    self.__action_state.commands.append(text)

  def echo_expression(self, expression, output_artifact):
    if output_artifact.filename.startswith("mem/"):
      self.add_output(output_artifact)
      varname = self.__state_map.varname(output_artifact)
      return "%s=%s" % (varname, expression)
    else:
      filename = self.artifact_filename_expression(output_artifact)
      return "echo %s > %s" % (expression, filename)

  def add_input(self, artifact):
    artifact = _canonicalize_artifact(artifact)
    if artifact not in self.__action_state.inputs:
      self.__action_state.inputs.add(artifact)

      if not artifact.filename.startswith("mem/") and \
         not artifact.filename.startswith("env/"):
        self.__action_state.input_names.add(
          self.artifact_filename_expression(artifact))

  def add_output(self, artifact):
    if artifact not in self.__action_state.outputs:
      self.__action_state.outputs.add(artifact)

      if artifact.filename.startswith("mem/"):
        self.__action_state.output_vars.add(
            self.__state_map.varname(artifact))
      elif not artifact.filename.startswith("env/"):
        self.__action_state.output_names.add(
            self.artifact_filename_expression(artifact))

  def artifact_filename_expression(self, artifact):
    artifact = _canonicalize_artifact(artifact)
    if artifact.action is self.__action_state.action:
      self.add_output(artifact)
    else:
      self.add_input(artifact)

    if artifact.filename.startswith("mem/") or \
       artifact.filename.startswith("env/"):
      raise NotImplementedError("Moving memory artifacts to disk in scripts.")

    if artifact.configured_name is None:
      filename = artifact.filename
    else:
      # Can't use artifact.real_name() because it won't properly quote the
      # results.  We need to quote the literal parts but *not* quote the
      # derived parts.
      parts = []
      for part in artifact.configured_name:
        if isinstance(part, Artifact):
          parts.append(self.artifact_content_expression(part))
        else:
          parts.append(pipes.quote(part))
      filename = "".join(parts)

    if filename.startswith("src"):
      return filename
    else:
      return "${prefix}" + filename

  def artifact_content_expression(self, artifact):
    artifact = _canonicalize_artifact(artifact)
    self.add_input(artifact)
    if artifact.filename.startswith("mem/"):
      varname = self.__state_map.varname(artifact)
      return "${%s}" % varname
    elif artifact.filename.startswith("env/set/"):
      # Is there any shell magic to make this shorter?
      return "$(test \"${%s+set}\" = set && echo true || echo false)" % \
             artifact.filename[8:]
    elif artifact.filename.startswith("env/"):
      return "${%s}" % artifact.filename[4:]
    else:
      return "$(<%s)" % self.artifact_filename_expression(artifact)

  def get_disk_directory_path(self, dir):
    if dir.startswith("mem/") or dir.startswith("env/"):
      raise ValueError("Not a disk directory: " + dir)
    if dir.startswith("src"):
      return dir
    else:
      return "${prefix}" + dir

  def set_status(self, status_expression):
    self.__action_state.status_expression = status_expression

  def enter_conditional(self, expression, required_artifacts_for_expression):
    raise NotImplementedError

  def enter_else(self):
    raise NotImplementedError

  def leave_conditional(self):
    raise NotImplementedError

class ScriptBuilder(object):
  def __init__(self):
    self.__state_map = _ScriptStateMap()
    self.__phases = []
    for _ in xrange(len(_PHASE_NAMES)):
      self.__phases.append([])

  def __add_artifact(self, artifact, phase):
    typecheck(artifact, Artifact)

    action = artifact.action
    if action is None:
      return

    action_state = self.__state_map.action_state(action)
    if action_state.phase <= phase:
      # Already queued.
      return

    for input in action_state.inputs:
      self.__add_artifact(input, phase)

    if action_state.phase != _NO_PHASE:
      self.__phases[action_state.phase].remove(action_state)
    action_state.phase = phase
    self.__phases[phase].append(action_state)

  def add_rule(self, rule):
    typecheck(rule, Rule)
    rule.expand_once()
    for artifact in rule.outputs:
      self.__add_artifact(artifact, _BUILD_PHASE)

  def add_test(self, test):
    typecheck(test, Test)
    test.expand_once()
    self.__add_artifact(test.test_result_artifact, _TEST_PHASE)
    self.__add_artifact(test.test_output_artifact, _TEST_PHASE)

  def write(self, out):
    made_dirs = set()

    out.write(_SCRIPT_INTRO)

    for phase in xrange(len(self.__phases)):
      out.write("# %s\n" % ("=" * 68))
      out.write("# %s phase\n" % _PHASE_NAMES[phase])
      out.write("\n")

      out.write("if test \"$do_%s\" = yes; then\n" % _PHASE_NAMES[phase])
      out.write("\n")

      for action_state in self.__phases[phase]:
        self.__write_action(action_state, out, made_dirs)

      out.write("fi\n")

  def __write_action(self, action_state, out, made_dirs):
    action = action_state.action

    dirty_tests = []
    for input in action_state.input_names:
      for output in action_state.output_names:
        dirty_tests.append("test %s -nt %s" % (input, output))
    for output_var in action_state.output_vars:
      dirty_tests.append("test -z \"${%s+set}\"" % output_var)
    if dirty_tests:
      out.write("  if ")
      out.write(" ||\n     ".join(dirty_tests))
      out.write("; then\n")
      indent = "    "
    else:
      indent = "  "

    out.write(indent + "echo ")
    if action_state.status_expression is not None:
      out.write("-n ")
    out.write(pipes.quote("%s: %s" % (action.verb, action.name)))
    out.write("\n")

    for output in action_state.output_names:
      dirname = os.path.dirname(output)
      if dirname not in made_dirs:
        made_dirs.add(dirname)
        out.write("%smkdir -p %s\n" % (indent, dirname))

    for command in action_state.commands:
      out.write("%s%s\n" % (indent, command))

    if action_state.status_expression is not None:
      out.write("%secho '' %s\n" % (indent, action_state.status_expression))

    for output_var in action_state.output_vars:
      out.write("%swrite_to_cache %s\n" % (indent, output_var))

    if dirty_tests:
      out.write("  fi\n")
    out.write("\n")
