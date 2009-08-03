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

"""
SEBS expects to be run from a directory with the following layout:
  bin      public binaries
  include  public header files
  lib      public libraries
  share    runtime data
  src      original source code
  tmp      intermediate build files

Before building, src is the only directory that is populated.  SEBS will
automatically create the others if they are not present.

src contains all of the source code for all projects.  It may be arbitrarily
large.  SEBS will never attempt to scan the whole thing -- the user must always
specify a particular build rule in a particular subdirectory.

bin, include, lib, and share contain the final outputs of the build.  The
contents of these directories are appropriate for installation, e.g. by copying
to the corrosponding directories under /usr or /usr/local.

tmp contains intermediate files produced by the build, e.g. object files,
private libraries, test progams, dependency files, generated code, and more.
The contents of this directory should never be modified except by invoking SEBS.
"""

import traceback

from sebs.helpers import typecheck

class DefinitionError(Exception):
  """Indicates that the SEBS build definition file was invalid."""
  pass

class Artifact(object):
  """Represents a file involved in the build process.  May be a source file
  or a generated file.

  Do not construct Artifacts directly.  Use the methods of Context
  (accessible as self.context in the body of any Rule) to create artifacts.

  Attributes:
    filename      Name of the file relative to the top of the project.
    action        The Action which creates this file, or None if this is not
                  a generated file.  If the file is generated, then it may not
                  actually exist yet; the Action is a placeholder."""

  def __init__(self, filename, action):
    typecheck(filename, basestring)
    typecheck(action, Action)

    self.filename = filename
    self.action = action

  def contents(self):
    """Returns a ContentToken for this Artifact, which can be used when building
    a SubprocessCommand to say that the contents of the file should be
    used as an argument to the command."""

    return ContentToken(self)

  def __repr__(self):
    return "<Artifact '%s'>" % self.filename

class ContentToken(object):
  """A placeholder for the contents of a file.  See Artifact.contents() and
  SubprocessCommand.

  Attributes:
    artifact   The Artifact for which this represents the contents."""

  def __init__(self, artifact):
    typecheck(artifact, Artifact)
    self.artifact = artifact

class CommandBase(object):
  """Dummy class used for type checking.  Command (in command.py) is the only
  direct subclass."""
  pass

class Action(object):
  """Represents a step in the build process, which has some inputs and some
  outputs.

  Attributes:
    rule       Rule which defined this action.
    verb       A simple verb indicating what the action is doing, like "compile"
               or "link" or "test".  This forms part of the message printed
               to the console when the action is executed.
    name       The name of the thing being operated upon.  This forms part of
               the message printed to the console when the action is executed.
               If None, the name of the rule is used.
    command    A Command to execute in order to build the outputs from
               the inputs.  Must be set using set_command(), since when a new
               Action is constructed its output Artifacts don't exist yet, and
               the command probably depends on the output Artifacts."""

  def __init__(self, rule, verb = "build", name = None):
    typecheck(rule, Rule)
    typecheck(verb, basestring)
    typecheck(name, basestring)

    self.rule = rule
    self.verb = verb
    self.__name = name
    self.command = None

  def __get_name(self):
    if self.__name is None:
      return self.rule.name
    else:
      return self.__name

  name = property(__get_name)

  def set_command(self, command):
    typecheck(command, CommandBase)
    self.command = command

  def __repr__(self):
    return "<Action '%s:%s'>" % (self.verb, self.name)

class Context(object):
  """Class representing the current SEBS context.  Every Rule object is
  attached to some Context, which is stored in the Rule's "context" field.
  If this Context is not explicitly passed to the Rule's constructor, then the
  "current context" at the time when the Rule was constructed is used.  This
  context corresponds to the SEBS file which is currently being loaded.

  The Context is also used to construct Actions and Artifacts.

  Attributes:
    filename       The name of the SEBS file that this context is associated
                   with, relative to the top of the source tree (the "src"
                   directory).
    full_filename  Like filename, but includes the full path of the file
                   (either absolute or relative to the directory where SEBS
                   was invoked).  Useful for error messages."""

  __current_context = None

  def run(self, function):
    """Set the context as the current context and then run the given
    function.  After the function completes, the current context is reverted
    to the previous current context before run() returns."""

    old_context = Context.__current_context
    Context.__current_context = self
    try:
      return function()
    finally:
      Context.__current_context = old_context

  @staticmethod
  def current():
    """Get the current context."""

    return Context.__current_context

  def local_filename(self, artifact):
    """Given an artifact, returns its package-relative filename, or None if
    it is not in this package.  Thus, given an artifact returned by
    source_artifact(), intermediate_artifact(), or memory_artifact(), this
    will return the original filename passed to the corresponding method.  As
    a convenience, if the parameter is a string, it is returned verbatim --
    this means that you can call local_filename() on inputs provided by the
    user which may be either file names or artifacts."""

    raise NotImplementedError

  def source_artifact(self, filename):
    """Returns an Artifact representing a source file.  The filename must be
    given relative to the directory containing the SEBS file.  If called
    multiple times with the same file, the same Artifact object is returned.
    As a convenience, if the parameter is actually an Artifact, it is simply
    returned verbatim -- this is usually what you want when the user specified
    an Artifact where a source file name was expected."""

    raise NotImplementedError

  def intermediate_artifact(self, filename, action):
    """Returns an Artifact representing an intermediate artifact which will be
    generated at build time by the given action and placed in the tmp
    directory.

    Parameters:
      filename    The name of the generated file, relative to the SEBS file's
                  tmp directory (which is derived by taking the source directory
                  and replacing 'src' with 'tmp').  In other words, each
                  directory in the source tree has its own namespace for
                  intermediate files.
      action      The action which generates this artifact."""

    raise NotImplementedError

  def memory_artifact(self, filename, action):
    """Like intermediate_artifact(), but creates an artifact which will be
    stored in memory rather than on disk.  Between invocations of SEBS, all
    such files will be stored in a single combined database file.  This is
    good to use for small artifacts, especially ones storing command exit codes
    or command-line flags for other commands (i.e. ones you'd use with
    ContentToken).  Memory artifacts are stored in a virtual subdirectory
    called "mem".  "mem" is a sibling of "src" and "tmp" with parallel
    structure, but is not stored on the physical disk.  Memory artifacts can
    only store text, not binary data."""

    raise NotImplementedError

  def output_artifact(self, directory, filename, action):
    """Returns an Artifact representing an output artifact which is suitable
    for installation.

    Parameters:
      directory    Indicates the top-level output directory where this artifact
                   will be written, e.g. 'bin' or 'lib'.
      filename     The output file name relative to the output directory.
      action       The action which generates this output."""

    raise NotImplementedError

  def action(self, *vargs, **kwargs):
    """Returns a new Action.  The caller should call the result's set_command()
    method to set the command which implements the action.  The parameters
    correspond to the parameters to the Action constructor, although you should
    not call the Action constructor directly."""

    raise NotImplementedError

class Rule(object):
  """Base class for a rule which can be built.  Generally, SEBS files contain
  a list of rules, where each rule expands to a set of actions.  So, a rule
  might define a C++ library, and consists of several actions which compile
  each source file into an object file and link them together.

  Attributes:
    context The Context in which the Rule was created.
    line    The line number where the rule was defined.
    label   The variable name assigned to this rule in the .sebs file, or None
            if the rule was anonymous.
    outputs List of Artifacts which should be built when this Rule is specified
            on the SEBS command line.  It is the responsibility of the Rule
            subclass to initialize this attribute.  Normally this attribute
            is not initialized until expand_once() has been called."""

  def __init__(self, context=None):
    typecheck(context, Context)

    if context is None:
      context = Context.current()
      if context is None:
        raise AssertionError(
          "Cannot create a Rule when not parsing a SEBS file.")

    self.context = context
    self.line = -1
    self.label = None
    self.__expanded = False

    for file, line, function, text in traceback.extract_stack():
      if file == context.full_filename:
        self.line = line
        # Note that we end up iterating from the top of the stack to the bottom,
        # but we want to use the innermost match, so we want to continue the
        # loop here and repeatedly overwrite self.line.

  def __get_name(self):
    sebsfile = self.context.filename
    if sebsfile.endswith("/SEBS"):
      sebsfile = sebsfile[:-5]
    if self.label is None:
      return "%s:%d" % (sebsfile, self.line)
    else:
      return "%s:%s" % (sebsfile, self.label)

  name = property(__get_name)

  def _expand(self):
    """Expand the Rule to build its Action graph.  This is called the first
    time expand_once() is called.  Subclasses should override this."""
    raise NotImplementedError

  def expand_once(self):
    """Called to build the Rule's action graph.  The first time this is called,
    self._expand() will be called; subsequent calls have no effect.  Subclasses
    should override _expand() to construct the action graph for the rule when
    called, placing a list of the final outputs in self.outputs.  During
    _expand(), a Rule must call expand_once() on each of its direct
    dependencies."""

    # TODO(kenton):  Detect recursion?
    if not self.__expanded:
      self._expand()
      self.__expanded = True

class Test(Rule):
  """A special kind of Rule that represents a test.

  Attributes (in addition to Rule's attributes):
    test_result_artifact  An artifact which will contain the text "true" if
                          the test passes or "false" if it fails.  (Hint:
                          Use SuprocessCommand's capture_exit_status to generate
                          this.)
    test_output_artifact  An artifact which will contain the test's console
                          output, useful for debugging."""
