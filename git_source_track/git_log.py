#!/usr/bin/env python3

import os
import shlex
import sys
import tempfile

import sh


def _get_commits(fname, rev_range):
    # Ask for the commit and the timestamp
    # .. the timestamp doesn't guarantee ordering, but good enough
    
    args = ['log', '--follow', '--pretty=%ct %h']
    if rev_range:
        args.append(rev_range)
    
    args.append(fname)
    
    for c in sh.git(*args, _tty_out=False, _iter=True):
        c = c.strip().split()
        yield int(c[0]), c[1]

def git_log(cfg, filenames, rev_range=None):
    '''
        A git log implementation that allows more flexibility:
        
        - Follow multiple files
        - Exclude commits we don't want to see
    '''
    
    if len(filenames) == 0:
        print("Specify at least one file to log")
        
    elif len(filenames) == 1 and not cfg.excluded_commits:
        if rev_range:
            cmd = 'git log --follow -p %s %s' % (rev_range, filenames[0])
        else:
            cmd = 'git log --follow -p %s' % (filenames[0])
        
        os.system(cmd)
    else:
        # Use git log to generate lists of commits for each file, sort
        commits = []
        for fname in filenames:
            commits += _get_commits(fname, rev_range)
            
        if not len(commits):
            return
        
        # Sort the lists (python's sort is stable)
        if len(filenames) > 1:
            commits.sort(reverse=True)
        
        # Uniquify (http://www.peterbe.com/plog/uniqifiers-benchmark)
        seen = set()
        seen_add = seen.add
        commits = [c for c in commits if not (c in seen or seen_add(c))]

        # Finally, display them
        tname = None
        
        try:
            file_list = ' '.join(shlex.quote(fname) for fname in filenames)
            
            with tempfile.NamedTemporaryFile(mode='w', delete=False) as fp:
                tname = fp.name
                for _, commit in commits:
                    if not cfg.is_commit_excluded(commit):
                        fp.write('git log -p -1 --color %s %s\n' % (commit, file_list))
                    
            with open(tname) as fp:
                print(fp.read())
                    
            # Use os.system to make our lives easier
            os.system('bash %s | less -FRX' % tname)
        finally:
            if tname:
                os.unlink(tname)

