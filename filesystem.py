# Scalable Extensible Build System
# Copyright (c) 2009 Kenton Varda.  All rights reserved.

import os
import time

from sebs.helpers import typecheck

class Directory(object):
  """Abstract base class for a directory in which builds may be performed."""
  
  def __init__(self):
    pass
  
  def exists(self, filename):
    """Check if the given file exists."""
    raise NotImplementedError
  
  def getmtime(self, filename):
    """Get the time at which the file was last modified, in seconds since
    1970."""
    raise NotImplementedError

  def touch(self, filename, mtime=None):
    """Set the modification time of the file to the current time, or to mtime
    if given."""
    raise NotImplementedError

  def execfile(self, filename, context):
    """Execute the file as a Python script.  "context" is a dict containing
    pre-defined global variables.  On return, it will additionally contain
    variables defined by the script."""
    raise NotImplementedError

class DiskDirectory(Directory):
  def __init__(self, path):
    typecheck(path, basestring)
    
    super(DiskDirectory, self).__init__()
    
    self.__path = os.path.normpath(path)
  
  def exists(self, filename):
    return os.path.exists(os.path.join(self.__path, filename))
  
  def getmtime(self, filename):
    return os.path.getmtime(os.path.join(self.__path, filename))

  def touch(self, filename, mtime=None):
    path = os.path.join(self.__path, filename)
    if mtime is None:
      os.utime(path, None)
    else:
      os.utime(path, (mtime, mtime))
  
  def execfile(self, filename, globals):
    # Can't just call execfile() because we want the filename in tracebacks
    # to exactly match the filename parameter to this method.
    file = open(os.path.join(self.__path, filename), "rU")
    content = file.read()
    file.close()
    ast = compile(content, filename, "exec")
    exec ast in globals

class VirtualDirectory(Directory):
  def __init__(self):
    super(VirtualDirectory, self).__init__()
    self.__files = {}
  
  def add(self, filename, mtime, content):
    typecheck(filename, basestring)
    typecheck(content, basestring)
    
    if isinstance(mtime, int):
      mtime = float(mtime)
    else:
      typecheck(mtime, float)
    self.__files[filename] = (mtime, content)
  
  def exists(self, filename):
    typecheck(filename, basestring)
    return filename in self.__files
  
  def getmtime(self, filename):
    typecheck(filename, basestring)
    if filename not in self.__files:
      raise os.error("File not found: " + filename)
    (mtime, content) = self.__files[filename]
    return mtime

  def touch(self, filename, mtime=None):
    typecheck(filename, basestring)
    if filename not in self.__files:
      raise os.error("File not found: " + filename)
    if mtime is None:
      mtime = time.time()
    oldtime, content = self.__files[filename]
    self.__files[filename] = (mtime, content)

  def execfile(self, filename, globals):
    typecheck(filename, basestring)
    if filename not in self.__files:
      raise os.error("File not found: " + filename)
    (mtime, content) = self.__files[filename]
    # Can't just exec because we want the filename in tracebacks
    # to exactly match the filename parameter to this method.
    ast = compile(content, filename, "exec")
    exec ast in globals
