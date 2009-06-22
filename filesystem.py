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
import time

from sebs.helpers import typecheck

class Directory(object):
  """Abstract base class for a directory in which builds may be performed."""
  
  def __init__(self):
    pass
  
  def exists(self, filename):
    """Check if the given file exists, returning true or false."""
    raise NotImplementedError
  
  def isdir(self, filename):
    """Check if the given file is a directory, returning true or false.  If
    the file doesn't exist, this returns false."""
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

  def get_disk_path(self, filename):
    """If the file is a real, on-disk file, return its path, suitable to be
    passed to open() or other file I/O routines.  If the file is not on disk,
    throws an exception.  If the file does not exist, this method may throw
    an exception or it may return an on-disk path that does not exist."""
    raise IOError("Not a disk file: %s" % filename)

class DiskDirectory(Directory):
  def __init__(self, path):
    typecheck(path, basestring)
    
    super(DiskDirectory, self).__init__()
    
    self.__path = os.path.normpath(path)
  
  def exists(self, filename):
    return os.path.exists(os.path.join(self.__path, filename))
  
  def isdir(self, filename):
    return os.path.isdir(os.path.join(self.__path, filename))
  
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

  def get_disk_path(self, filename):
    return os.path.join(self.__path, filename)

class VirtualDirectory(Directory):
  def __init__(self):
    super(VirtualDirectory, self).__init__()
    self.__files = {}
    self.__dirs = set()
  
  def add(self, filename, mtime, content):
    """Add a file to the VirtualDirectory.  Automatically adds parent
    directories as needed."""
    typecheck(filename, basestring)
    typecheck(content, basestring)
    
    if isinstance(mtime, int):
      mtime = float(mtime)
    else:
      typecheck(mtime, float)
    self.__files[filename] = (mtime, content)
    self.add_directory(os.path.dirname(filename))
  
  def add_directory(self, filename):
    """Add a subdirectory to the VirtualDirectory.  Automatically adds parent
    directories as needed."""
    typecheck(filename, basestring)
    if filename != "":
      self.__dirs.add(filename)
      self.add_directory(os.path.dirname(filename))
  
  def exists(self, filename):
    typecheck(filename, basestring)
    return filename in self.__files or filename in self.__dirs
  
  def isdir(self, filename):
    typecheck(filename, basestring)
    return filename in self.__dirs
  
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
    

class MappedDirectory(Directory):
  """A directory which wraps some other set of directories, choosing which
  one to use based on filename.  A Mapping object is used to map each filename
  to some file in some other Directory, then the the same method is called on
  that file."""
  
  class Mapping(object):
    """Class which maps filenames to other locations for MappedDirectory."""
    
    def map(self, filename):
      """Maps the filename to a file in some other Directory object.  Returns a
      (directory, filename) tuple."""
      raise NotImplementedError
  
  def __init__(self, mapping):
    super(MappedDirectory, self).__init__()
    self.__mapping = mapping
  
  def __do_mapping(self, method, filename, *args):
    (directory, mapped_name) = self.__mapping.map(filename)
    return getattr(directory, method)(mapped_name, *args)
  
  def exists(self, filename):
    return self.__do_mapping("exists", filename)
  
  def isdir(self, filename):
    return self.__do_mapping("isdir", filename)
  
  def getmtime(self, filename):
    return self.__do_mapping("getmtime", filename)

  def touch(self, filename, mtime=None):
    return self.__do_mapping("touch", filename, mtime)

  def execfile(self, filename, context):
    # TODO(kenton):  The exec'd file will see its own name as the post-mapping
    #   name, not the virtual name.  Do we care?
    return self.__do_mapping("execfile", filename, context)

  def get_disk_path(self, filename):
    return self.__do_mapping("get_disk_path", filename)
