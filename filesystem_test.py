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

import os
import shutil
import tempfile
import time
import unittest

from sebs.filesystem import Directory, DiskDirectory, VirtualDirectory, \
                            MappedDirectory

class DirectoryTest(object):
  """Base class for DiskDirectoryTest and VirtualDirectoryTest.  Defines test
  cases that apply to both.  Does not subclass unittest.TestCase because we
  do not want the test loader to try to instantiate this class automatically.
  
  The subclass must define a member called "dir" which is the directory being
  tested.  It must also implement addFile()."""
  
  def addFile(self, name, mtime, content):
    """Add a file to self.dir."""
    raise NotImplementedError
  
  def addDirectory(self, name):
    """Add a directory to self.dir."""
    raise NotImplementedError
  
  def testExists(self):
    self.addFile("foo", 123, "Hello world!")
    
    self.assertTrue(self.dir.exists("foo"))
    self.assertFalse(self.dir.exists("bar"))
    
  def testIsdir(self):
    self.addDirectory("foo/bar/baz")
    self.assertTrue(self.dir.isdir("foo"))
    self.assertTrue(self.dir.isdir("foo/bar"))
    self.assertTrue(self.dir.isdir("foo/bar/baz"))
    self.assertFalse(self.dir.isdir("nosuchdir"))

    self.addFile("somefile", 123, "Hello world!")
    self.assertFalse(self.dir.isdir("somefile"))
  
  def testGetMTime(self):
    self.addFile("foo", 123, "Hello world!")
    
    self.assertEquals(123, self.dir.getmtime("foo"))
    
    # Make sure touch() sets mtime to the current time.
    start = time.time()
    self.dir.touch("foo")
    end = time.time()
    mtime = self.dir.getmtime("foo")
    # Give a one-second buffer in case the filesystem rounds floating-point
    # times to an integer.
    self.assertTrue(start - 1 <= mtime and mtime <= end + 1)
    
    # Try a touch with an explicit time.
    self.dir.touch("foo", 321)
    self.assertEquals(321, self.dir.getmtime("foo"))
  
  def testExecfile(self):
    self.addFile("foo", 123,
      "x = i + 5\n"
      "y = 'foo'\n"
      "import traceback\n"
      "filename, _, _, _ = traceback.extract_stack(limit = 1)[0]\n")
    
    vars = {"i": 12}
    self.dir.execfile("foo", vars)
    self.assertTrue("x" in vars)
    self.assertEqual(17, vars["x"])
    self.assertTrue("y" in vars)
    self.assertEqual("foo", vars["y"])
    self.assertTrue("filename" in vars)
    # See TODO in MappedDirectory.execfile().
    if not isinstance(self.dir, MappedDirectory):
      self.assertEqual("foo", vars["filename"])

class DiskDirectoryTest(DirectoryTest, unittest.TestCase):
  def setUp(self):
    self.tempdir = tempfile.mkdtemp()
    self.dir = DiskDirectory(self.tempdir)
    super(DiskDirectoryTest, self).setUp()

  def tearDown(self):
    super(DiskDirectoryTest, self).tearDown()
    shutil.rmtree(self.tempdir)
  
  def addFile(self, name, mtime, content):
    path = os.path.join(self.tempdir, name)
    f = open(path, "wb")
    f.write(content)
    f.close()
    os.utime(path, (mtime, mtime))

  def addDirectory(self, name):
    os.makedirs(os.path.join(self.tempdir, name))

  def testGetDiskPath(self):
    self.assertEquals(os.path.join(self.tempdir, "foo/bar"),
                      self.dir.get_disk_path("foo/bar"))

class VirtualDirectoryTest(DirectoryTest, unittest.TestCase):
  def setUp(self):
    self.dir = VirtualDirectory()
    super(VirtualDirectoryTest, self).setUp()

  def addFile(self, name, mtime, content):
    self.dir.add(name, mtime, content)

  def addDirectory(self, name):
    self.dir.add_directory(name)

  def testGetDiskPath(self):
    self.assertRaises(IOError, self.dir.get_disk_path, "foo/bar")

class MappedDirectoryTest(DirectoryTest, unittest.TestCase):
  class MappingImpl(MappedDirectory.Mapping):
    def __init__(self, prefix, real_dir):
      super(MappedDirectoryTest.MappingImpl, self).__init__()
      self.__prefix = prefix
      self.__real_dir = real_dir
    
    def map(self, filename):
      return (self.__real_dir, os.path.join(self.__prefix, filename))
  
  def setUp(self):
    self.virtual_dir = VirtualDirectory()
    self.dir = MappedDirectory(
        MappedDirectoryTest.MappingImpl("mapped_prefix", self.virtual_dir))
    super(MappedDirectoryTest, self).setUp()

  def addFile(self, name, mtime, content):
    self.virtual_dir.add(os.path.join("mapped_prefix", name), mtime, content)

  def addDirectory(self, name):
    self.virtual_dir.add_directory(os.path.join("mapped_prefix", name))

  def testGetDiskPath(self):
    self.assertRaises(IOError, self.dir.get_disk_path, "foo/bar")

if __name__ == "__main__":
  unittest.main()
