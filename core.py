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
import os.path

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

  def derived_artifact(self, artifact, extension, action):
    """Returns an artifact whose name is derived from the given artifact, with
    the file extension replaced with |extension| (a string).  The new artifact
    behaves like an intermediate artifact."""

    typecheck(artifact, Artifact)
    typecheck(extension, basestring)
    typecheck(action, Action)

    filename = self.local_filename(artifact)
    if filename is None:
      filename = artifact.filename.replace("/", "_")
    basename, _ = os.path.splitext(filename)
    return self.intermediate_artifact(basename + extension, action)

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

class _RuleArgs(object):
  """Dummy class.  See below."""
  pass

class ArgumentSpec(object):
  """Used to specify the arguments accepted by a function, usually a constructor
  for a subclass of Rule.  ArgumentSpec allows you to specify a set of parameter
  names and types with simple syntax:

    spec = ArgumentSpec(
        foo = str,        # "foo" is a required argument of type string.
        bar = [int],      # "bar" is a required list of integers.
        baz = (int, 12))  # "baz" is an optional integer that defaults to 12.

    def some_function(**kwargs):
      # Validate the arguments.  Throws TypeError if anything is wrong.
      # Returns an object whose attributes are the arguments.
      args = spec.validate("some_function", context, kwargs)

      do_something(args.foo, args.bar, args.baz)

    # Valid calls to some_function.
    some_function(foo = "hello", bar = [1, 3], baz = 42)
    some_function(foo = "world", bar = [])

    # INVALID calls -- these throw exceptions.
    some_function(foo = "bad")               # Missing required attribute "bar".
    some_function(foo = 123, bar = [])       # "foo" has wrong type.
    some_function(foo = "x", bar = ["str"])  # "bar" has element of wrong type.
    some_function(foo="", bar=[], qux = 1)   # "qux" is not an allowed argument.

  As you can see from the example, each argument to ArgumentSpec's constructor
  corresponds to one of the arguments that will be accepted by validate().  The
  value of each constructor argument is a type or a tuple.  If it is a type,
  then the argument is required and must be an instance of that type.  If it is
  a tuple, then the first element of the tuple is the type and the second
  element is the default value; if the argument is omitted, the default will be
  used.  Additionally, instead of a type you may specify a list with one
  element, where that element is a type.  This says that the argument must be a
  list of values of that type.

  ArgumentSpec treats the "Artifact" type specially:  the caller is allowed to
  pass either an actual Artifact object or a string.  In the latter case, the
  string is interpreted as a source file name in the current package.
  ArgumentSpec.validate() automatically passes such strings to
  context.source_artifact() to obtain Artifact objects.  So, the object returned
  by validate() will only contain Artifact objects for such fields.  A similar
  process applies to lists of Artifacts -- each element in the list may be
  either a string or an Artifact.

  Note that arguments validated via ArgumentSpec are always keyword arguments,
  never positional.  SEBS rule constructors never accept positional arguments.
  """

  def __init__(self, **kwargs):
    self.spec_map = kwargs

  def extend(self, **kwargs):
    copy = self.spec_map.copy()
    copy.update(kwargs)
    return ArgumentSpec(**copy)

  def validate(self, function_name, context, args):
    result = _RuleArgs()

    for name, value in args.items():
      if name not in self.spec_map:
        raise TypeError(
            "%s() got an unexpected keyword argument '%s'" %
            (function_name, name))

      spec = self.spec_map[name]
      if isinstance(spec, tuple):
        arg_type = spec[0]
      else:
        arg_type = spec
      result.__dict__[name] = self.__validate_arg(
          function_name, name, context, value, arg_type)

    for name, spec in self.spec_map.items():
      if name not in result.__dict__:
        if isinstance(spec, tuple):
          result.__dict__[name] = spec[1]
        else:
          raise TypeError("%s() requires missing argument '%s' %s" %
                          (function_name, name))

    return result

  def __validate_arg(self, function_name, arg_name, context, value, arg_type):
    if isinstance(arg_type, list):
      return [
          self.__validate_arg(function_name, arg_name, context, e, arg_type[0])
          for e in value ]
    elif arg_type is Artifact:
      if isinstance(value, basestring):
        return context.source_artifact(value)
      elif isinstance(value, Artifact):
        return value
      else:
        raise TypeError("%s(), argument '%s':  Expected source file name or "
                        "artifact, got: %s" % (function_name, arg_name, value))
    else:
      if isinstance(value, arg_type):
        return value
      else:
        raise TypeError("%s(), argument '%s':  Expected %s, got: %s" %
                        (function_name, arg_name, arg_type, value))

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
            is not initialized until expand_once() has been called.

  When subclassing Rule, do NOT define an __init__() method.  Instead, you
  must specify your class's constructor parameters via a static field
  argument_spec, which must be an instance of ArgumentSpec.  For example:

    class MyTarget(sebs.Rule):
      argument_spec = sebs.ArgumentSpec(
          name = str,               # Argument "name" is a string.
          srcs = [sebs.Artifact])   # Argument "srcs" is a list of files.

      def _expand(self, args):
        # Constructor arguments can be accessed as args.name and args.srcs.
  """

  argument_spec = ArgumentSpec()

  def __init__(self, context=None, **kwargs):
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

    self.__args = self.argument_spec.validate(
        str(self.__class__), self.context, kwargs)

  def __get_name(self):
    sebsfile = self.context.filename
    if sebsfile.endswith("/SEBS"):
      sebsfile = sebsfile[:-5]
    if self.label is None:
      return "%s:%d" % (sebsfile, self.line)
    else:
      return "%s:%s" % (sebsfile, self.label)

  name = property(__get_name)

  def _expand(self, args):
    """Expand the Rule to build its Action graph.  This is called the first
    time expand_once() is called.  Subclasses should override this.  |args|
    is an object containing the validated constructor arguments, as returned
    by ArgumentSpec.validate()."""
    raise NotImplementedError

  def expand_once(self):
    """Called to build the Rule's action graph.  The first time this is called,
    self._expand() will be called; subsequent calls have no effect.  Subclasses
    should override _expand() to construct the action graph for the rule when
    called, placing a list of the final outputs in self.outputs.  During
    _expand(), a Rule must call expand_once() on each of its direct
    dependencies."""

    if self.__expanded is None:
      raise DefinitionError("Rule cyclically depends on self: %s" % self.name)
    elif not self.__expanded:
      self.__expanded = None
      self._expand(self.__args)
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
