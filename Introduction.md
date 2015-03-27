<font color='red'><b>WARNING:</b></font>  SEBS is very new (started in June 2009).  This document is incomplete and not all features discussed below are implemented yet.

# Contents #



# What is SEBS? #

SEBS stands for Scalable Extendable Build System.  SEBS serves a similar purpose to tools like make, autotool, Scons, Maven, and others.

# Goals #

SEBS has two primary goals which the developers believe are not adequately met by other open source build systems:

### Scalability ###

Most popular build systems assume that you only want to build one project at a time.  If you need to build program Foo which depends on library Bar, you are usually expected to build Bar separately and install it before you even think about building Foo.  A few systems will offer to automatically download and install the latest release of Bar for you, but even this can be too cumbersome.  What if you are developing Foo and you need to build it against the very latest code for Bar straight out of VCS?  Or even worse, what if you need to actively change Bar in order to add features needed by Foo?  With the traditional model, you must constantly switch projects, compile, install, and switch back.

With SEBS, you can simply put all the projects in one tree and it will automatically rebuild dependencies when they change.  Furthermore, SEBS is designed to work with truly massive source trees.  Imagine a tree containing literally thousands of separate -- but interdependent -- projects.  SEBS can handle this, because when SEBS is invoked it will only parse the definition for the particular target you are interested in and its dependencies.  It will not even look at directories in the source tree which are not relevant to your build.  With SEBS, there is no master build definition file for the source tree; instead, each individual project in the tree contains its own build files.

You can even put SEBS itself into your source tree, make modifications to it, and immediately use those modifications.  However, this should not often be needed due to the next feature.

### Extendability ###

Defining new build rules in SEBS -- for example, to support building a new language -- is easy.  SEBS build definition files are written in Python, and new rules are written as Python classes directly in those files (or imported from other files).  This contrasts with systems like automake, which can only be extended by modifying the automake implementation, or Maven, which requires you to implement new actions as "plugins" written in Java.  And while old-fashion `make` provides some limited extendability, it is nowhere near as flexible as what SEBS provides.

# Terminology #

**Target:**  A named output of the build, such as an executable program or a library.

**Rule:**  Defines how to build a particular target given some inputs.  For example, you may have a rule to build an executable program from a set of C++ source files.

**Rule class:**  A type of rule.  For example, you might define a rule class for building executable programs from C++ source files.  Rule classes are implemented as Python classes which subclass `Rule`.

**Artifact:**  Input or output of an action.  Usually, an artifact is a file on disk -- including source files, intermediate files, and output files.

**Action:**  A set of commands (usually, one command) that take some inputs and produce some outputs.

# Installation #

First, create a new, empty directory to be your SEBS working directory.  Then, execute the following commands from inside that directory:

```
mkdir src
hg clone https://sebs.googlecode.com/hg/ src/sebs
```

This places the SEBS source code in the subdirectory src/sebs.  We'll see why we do it this way in the next section.

Next, define an alias for SEBS:

```
alias sebs='PYTHONPATH=src python -m sebs.main'
```

Now, when you type `sebs`, the SEBS implementation will be invoked right out of the working directory.  Try using it to run the SEBS unit tests:

```
sebs test src/sebs
```

If you prefer to build a static executable to invoke rather than keep the SEBS code inside your working directory, you can do so:

```
sebs build src/sebs:sebs
```

This creates the executable file `bin/sebs` which you can then copy somewhere in your `PATH`.

# Working directory layout #

Since a SEBS working directory may contain multiple projects, no one project owns the top-level directory.  The top directory has subdirectories following the usual Unix style:  `bin`, `lib`, `include`, `tmp`, `src`, etc.   The `src` directory contains the source tree -- it typically has subdirectories for each project.  The `tmp` directory contains all intermediate files produced during the build, such as object files and generated code.  The other directories are where the final output goes.  Once the build is complete, installation is often just a matter of copying the contents of these directories to the corresponding locations in `/usr` or `/usr/local` (but SEBS can automate this too).

Here's an example of what a SEBS working directory containing [Google Protocol Buffers](http://protobuf.googlecode.com) might look like.  Note that Protocol Buffers depends on [Google Test](http://gtest.googlecode.com) and [zlib](http://www.zlib.org).  In this example we hypothetically imagine that Protocol Buffers has decided to provide a SEBS build definition file (not unthinkable since the maintainer of Protocol Buffers is also the creator of SEBS) while Google Test chooses to provide only a traditional autoconf-based build.  SEBS manages to glue Google Test in using an unofficial SEBS file provided by a third party (probably by the SEBS project itself).  Meanwhile, since zlib is almost always already installed on the host system and there is little need to modify it, we represent it with a stub SEBS definition file that just directs dependents to link against the installed copy.

```
bin/
  protoc                       # built program binary to be installed
lib/
  libprotobuf.so               # built shared library to be installed
  libprotobuf.a                # built static library to be installed
include/
  google/
    protobuf/
      descriptor.h             # copied public header file to be installed
      ...
tmp/
  google/
    protobuf/
      descriptor.o             # compiled object file
      descriptor_unittest      # compiled test program
      unittest.pb.cc           # generated code
      ...
src/
  google/                      # "namespace" directory, not owned by any project.
    protobuf/                  # Protocol Buffers project directory.
      SEBS                     # project-provided SEBS build file
      descriptor.cc            # source code
      descriptor.h             # original copy of header
      descriptor_unittest.cc   # unit test code
      unittest.proto           # more source code
      ...
  gtest/                       # Google Test project directory (dependency of protobuf)
    configure.ac               # traditional autoconf-based configure script
    Makefile.am                # traditional automake-based makefile
    ...
  sebs/                        # SEBS project directory
    ...
  ...                          # other projects
src-unofficial/                # unofficial third-party-provided SEBS files
  gtest/
    SEBS                       # unofficial SEBS build file for Google Test
src-installed/
  zlib/
    SEBS                       # stub SEBS file for installed zlib
```

# SEBS definition files #

SEBS definition files -- the SEBS equivalent of Makefiles -- are either called `SEBS` (all caps) or have the `.sebs` extension.  By convention, each package in the source tree contains a file `SEBS` which defines that package's public targets.  A package may also contain other SEBS definition files with the `.sebs` extension; typically these would be used to define reusable custom rule classes.  SEBS files are written in Python.

A typical SEBS file might look like:

```
# foo/SEBS

# Import targets and utilities from other packages and files.  Note that we
# assign these to names prefixed with underscores because this marks them private
# to the file; otherwise, other people could import these from our file.
_zlib = sebs_import("zlib:zlib")
_cpp = sebs_import("sebs/cpp.sebs")

# Defines the library foo.  This will typically produce two outputs on Unix systems:
#   lib/libfoo.so
#   lib/libfoo.a
foolib = _cpp.Library("foo",
  # Compile these files to produce the foo library.
  srcs = [ "foo.cc", "bar.cc", "bar.h" ],
  # These headers may be included by other libraries.
  public_headers = [ "foo.h" ],
  # The foo library depends on zlib.
  deps = [ _zlib ])

# Defines the program "fooprog".  On unix, this will produce one output:
#   bin/fooprog
foo = _cpp.Binary("fooprog",
  srcs = [ "main.cc" ],
  deps = [ foolib ])

# Define a test.  This produces no public outputs, but can be run by SEBS.
foo_test = _cpp.Test(
  srcs = [ "foo_test.cc" ],
  deps = [ foolib ])

```

To compile the program "bin/fooprog", you might type:

```
sebs build src/foo:foo
```

If you omit the target name, all named targets in the package will be built:

```
sebs build src/foo
```

To include all subdirectories, add `/...`:

```
sebs build src/foo/...
```

To run all tests in the package and produce a list of passes and failures, you might type:

```
sebs test src/foo
```

Another project might depend on `foolib` like so:

```
# bar/SEBS

_cpp = sebs_import("sebs/cpp.sebs")

# OPTION 1
_foolib = sebs_import("foo:foolib")
bar = _cpp.Binary("bar",
  srcs = [ "bar.cc" ],
  deps = [ _foolib ])

# OPTION 2 -- this is equivalent
_foo = sebs_import("foo")
bar = _cpp.Binary("bar",
  srcs = [ "bar.cc" ],
  deps = [ _foo.foolib ])
```