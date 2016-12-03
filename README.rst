git-source-track
================

This is a tool that makes it easier to track source code changes between two
repositories. This tool was originally developed for use by the RobotPy project,
and made it easier for me to maintain a python port of various Java libraries.

This tool assumes there is an 'original' git repository, and a 'destination' git
repository that is being validated. There is assumed a one to one relationship
between various original and destination files. This tool provides quick and
easy shortcuts to allow you to record metadata in the destination files that
allow you to track changes in the source files:

* Record which file it comes from
* Mark the latest manually verified revision in the destination
* Allow viewing the latest modifications to the source file (if any)
* Update the revision metadata in the destination file

Install
-------

::

    pip install git-source-track

Configuration
-------------

Create a file called '.gittrack' in the root of the destination git repository
that has the following ini-style format::
    
    [git-source-track]
            
    # Original files
    upstream_root = ../path/to/files
    
    # Commit in original repository
    upstream_commit = xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
    
    # Files that are being validated 
    validation_root = path/to_files
    
    # (optional) Commits to exclude from git log output
    exclude_commits_file = foo/exclude_commits.txt

Now you can issue git commands and magic will happen!

Usage
-----

See the help command for more information.

::
    
    $ git source-track help

Known issues
------------

* Tool mostly tested using Python 3, but should work on Python 2
* Probably won't work on Windows, due to the use of the 'sh' package and because
  there are dependencies on unix-style tools
  * May work in Windows 10 posix environment
* Assumes destination files are python files
* Emits python style comments on destination files

Pull requests are welcome to fix any of these problems. :)

Author
------

Dustin Spicuzza (dustin@virtualroadside.com)

