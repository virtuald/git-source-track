
from __future__ import print_function

import os
from six.moves import shlex_quote
import tempfile

import sh

def _multi_output(commands):
    '''
        Shows output of multiple git commands
        
        .. make sure the output is shell-safe
    '''
    tname = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', delete=False) as fp:
            tname = fp.name
            for command in commands:
                fp.write(command)
                fp.write('\n')
            
        os.system('bash %s | less -FRX' % tname)
    finally:
        if tname:
            os.unlink(tname)

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

def git_diff(filenames, rev_range):
    commands = ['git diff --follow -w --color %s %s' % (rev_range, shlex_quote(f)) for f in filenames]
    _multi_output(commands)

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
        
        # Sort the results by timestamp
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
        try:
            os.chdir(git_toplevel)
            
            commands = []
            
            for commit in commits:
                if not cfg.is_commit_excluded(commit):
                    for i, fname in enumerate(sorted(fname_by_commit[commit])):
                        fname = shlex_quote(fname)
                        # git log --follow only allows a single filename, so
                        # merge the outputs together using separate commands
                        if i == 0:
                            commands.append('git log -p -1 --follow --color %s -- %s' % (commit, fname))
                        else:
                            commands.append('git log -p -1 --follow --color --pretty='' %s -- %s' % (commit, fname))
            
            _multi_output(commands)
            
        finally:
            os.chdir(oldcwd)
        


