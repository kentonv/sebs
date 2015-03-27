SEBS is a build system designed with two primary goals:

**Scalable:**  SEBS can operate on enormous source trees.  Many interdependent projects can be placed in a single large source tree and built via a single invocation of the build system.  This differs from traditional systems in which you must build and install all of a project's dependencies manually before you may build the dependent project.

**Extendable:**  New kinds of build rules (e.g. support for a new programming language) can be easily added by users without changing the implementation of SEBS itself.  SEBS definition files are written in Python, allowing them to contain general-purpose code.