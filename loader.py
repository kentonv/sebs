# Scalable Extensible Build System
# Copyright (c) 2009 Kenton Varda.  All rights reserved.

import os

from sebs.core import Rule, Artifact, Action, Context, DefinitionError
from sebs.filesystem import Directory
from sebs.helpers import typecheck

class _ContextImpl(Context):
  def __init__(self, loader, filename):
    typecheck(loader, Loader)
    typecheck(filename, basestring)
    
    self.__loader = loader
    self.filename = filename
    self.full_filename = os.path.join("src", filename)
    self.directory = os.path.dirname(filename)

  def source_artifact(self, filename):
    self.__validate_artifact_name(filename)
    
    return self.__loader.source_artifact(
      os.path.join("src", self.directory, filename))

  def intermediate_artifact(self, filename, action):
    self.__validate_artifact_name(filename)
    typecheck(action, Action)
    
    return self.__loader.derived_artifact(
      os.path.join("tmp", self.directory, filename), action)
  
  def output_artifact(self, directory, filename, action):
    typecheck(directory, basestring)
    self.__validate_artifact_name(filename)
    typecheck(action, Action)

    if directory not in ("bin", "include", "lib", "share"):
      raise DefinitionError(
        "'%s' is not a valid output directory." % directory)
    
    return self.__loader.derived_artifact(
      os.path.join(directory, filename), action)

  def action(self, *vargs, **kwargs):
    return Action(*vargs, **kwargs)
  
  def __validate_artifact_name(self, filename):
    typecheck(filename, basestring)
    normalized = os.path.normpath(filename).replace("\\", "/")
    if filename != normalized:
      raise DefinitionError(
        "File '%s' is not a normalized path name.  Please use '%s' "
        "instead." % (filename, normalized))

    if filename.startswith("../") or filename.startswith("/"):
      raise DefinitionError(
        "File '%s' points outside the surrounding directory.  To "
        "include a file from another directory, that directory must explicitly "
        "export it." % filename)

class BuildFile(object):
  def __init__(self, vars):
    self.__dict__.update(vars)

class Loader(object):
  def __init__(self, root_dir):
    typecheck(root_dir, Directory)
    
    self.__loaded_files = {}
    self.__source_artifacts = {}
    self.__derived_artifacts = {}
    self.__root_dir = root_dir

  def load(self, filename):
    """Load a SEBS file.  The filename is given relative to the root of
    the source tree (the "src" directory).  Returns an object whose fields
    correspond to the globals defined in that file."""
    
    typecheck(filename, basestring)
    
    normalized = os.path.normpath(filename).replace("\\", "/")
    if filename != normalized:
      raise DefinitionError(
        "'%s' is not a normalized path name.  Please use '%s' instead." %
        (filename, normalized))

    if filename.startswith("../") or filename.startswith("/"):
      raise DefinitionError(
        "'%s' is not within src." % filename)
    
    if filename in self.__loaded_files:
      existing = self.__loaded_files[filename]
      if existing is None:
        raise DefinitionError("File recursively imports itself: %s", filename)
      return existing
    
    context = _ContextImpl(self, filename)
    
    def run():
      vars = {
        "sebs_import": self.load,
        "Rule": Rule
      }
      self.__root_dir.execfile(context.full_filename, vars)
      return vars

    self.__loaded_files[filename] = None
    try:
      vars = context.run(run)
    finally:
      del self.__loaded_files[filename]
    
    # Delete "builtins".
    del vars["sebs_import"]
    del vars["Rule"]
    
    for name in vars.keys():
      if name.startswith("_"):
        # Delete private variable.
        del vars[name]
      elif isinstance(vars[name], Rule) and vars[name].context == context:
        # Set label on rule instance.
        vars[name].label = name

    build_file = BuildFile(vars)
    self.__loaded_files[filename] = build_file
    return build_file

  def source_artifact(self, filename):
    typecheck(filename, basestring)
    
    if filename in self.__source_artifacts:
      return self.__source_artifacts[filename]
    
    result = Artifact(filename, None)
    self.__source_artifacts[filename] = result
    return result

  def derived_artifact(self, filename, action):
    typecheck(filename, basestring)
    typecheck(action, Action)
    
    if filename in self.__derived_artifacts:
      raise DefinitionError(
        "Two different rules claim to build file '%s'.  Conflicting rules are "
        "'%s' and '%s'." %
        (filename, action.rule.name,
         self.__derived_artifacts[filename].action.rule.name))

    filename = os.path.normpath(filename).replace("\\", "/")
    result = Artifact(filename, action)
    self.__derived_artifacts[filename] = result
    return result
