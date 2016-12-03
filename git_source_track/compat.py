
#
# For information about atomic writes, see
# -> http://stupidpythonideas.blogspot.com/2014/07/getting-atomic-writes-right.html
#
# Basically, if you're using Python 3.3+, good to go. Otherwise
# we'll try our best, but no guarantees.
#

import os

if hasattr(os, 'replace'):      # Python 3.3+
    file_replace = os.replace
elif os.name != 'nt':           # Not Windows
    file_replace = os.rename
else:                           # Windows
    def file_replace(src, dst):
        try:
            os.unlink(dst)
        except FileNotFoundError:
            pass
        os.rename(src, dst)