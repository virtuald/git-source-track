
from __future__ import print_function

import os
from six.moves import shlex_quote
import tempfile

import sh


def _get_commits(fname, rev_range):
    # Ask for the commit, timestamp, and the filename in case it changed
    # .. the timestamp doesn't guarantee ordering, but good enough
    
    args = ['log', '--follow', '--pretty=%ct %H', '--name-only']
    if rev_range:
        args.append(rev_range)
    
    args.append(fname)
    it = sh.git(*args, _tty_out=False, _iter=True)
    
    while True:
        l1 = next(it).strip().split()
        next(it)
        l2 = next(it).strip()
        
        yield int(l1[0]), l1[1], l2

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
        # To show renames properly, we have to switch to the root
        # of the repository and then specify the potentially renamed file
        # for each commit
        oldcwd = os.getcwd()
        git_toplevel = str(sh.git('rev-parse', '--show-toplevel')).strip()
        
        # Use git log to generate lists of commits for each file, sort
        commit_data = []
        for fname in filenames:
            commit_data += _get_commits(fname, rev_range)
        
        if not len(commit_data):
            return
        
        # Sort the lists (python's sort is stable)
        if len(filenames) > 1:
            commit_data.sort(reverse=True)
        
        # Create an index of filenames per commit id
        fname_by_commit = {}
        for _, commit, fname in commit_data:
            fname_by_commit.setdefault(commit, []).append(fname)
        
        # Uniquify (http://www.peterbe.com/plog/uniqifiers-benchmark)
        seen = set()
        seen_add = seen.add
        commits = [c for _, c, _ in commit_data if not (c in seen or seen_add(c))]

        # Finally, display them
        tname = None
        
        try:
            os.chdir(git_toplevel)
            
            with tempfile.NamedTemporaryFile(mode='w', delete=False) as fp:
                tname = fp.name
                for commit in commits:
                    if not cfg.is_commit_excluded(commit):
                        file_list = ' '.join(shlex_quote(fname) for fname in fname_by_commit[commit])
                        fp.write('git log -p -1 --follow --color %s -- %s\n' % (commit, file_list))
            
            with open(tname) as fp:
                print(fp.read())
                    
            # Use os.system to make our lives easier
            os.system('bash %s | less -FRX' % tname)
        finally:
            if tname:
                os.unlink(tname)
            os.chdir(oldcwd)

