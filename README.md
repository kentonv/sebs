# OBSOLETE PROJECT

"Simple Extensible Build System"

This is a little build system I was toying with a very, very long time ago. Build files are actually parsed as Python (making it easy to extend) and the system supports compiling cross-compiling to multiple targets at once, including compiling tools for the host platform and then immediately turning around and using them as part of the cross-build.

Neat, but you should NOT use this, because I'm not maintaining it. Instead, consider:
* Google's [Bazel](http://bazel.io/), the recently-released open source version of Google's internal tools which inspired some (but not all) aspects of SEBS' design (I was a Google employee at the time).
* My own [Ekam](https://github.com/sandstorm-io/ekam), a radically different build tool I wrote later on which is actively developed and used by [Sandstorm.io](https://sandstorm.io).
