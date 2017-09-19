
from __future__ import print_function

import argparse
from contextlib import contextmanager
from functools import cmp_to_key
import inspect
import os
import posixpath
from os.path import abspath, basename, dirname, exists, join, normpath, relpath, split, splitext
import re
import sys
import tempfile
import time

from six.moves.configparser import RawConfigParser, NoSectionError, NoOptionError
from six.moves import input

import sh

from .compat import file_replace
from .git_log import git_log

invalid_hash = 'DOES_NOT_EXIST'
short_hash_sz = 12

cfg_section = 'git-source-track'

def git_commit_cmp(c1, c2):
    '''
        Sorting function that compares commits, falls back to time compare
        
        Returns <0 if c1 is older than c2
                0 if same commit
                >0 if c2 is older than c1
    '''
    ts1, c1 = c1
    ts2, c2 = c2
    
    if c1 == c2:
        return 0
    
    if sh.git('merge-base', '--is-ancestor',
              c1, c2, _ok_code=[0,1]).exit_code == 0:
        return -1
    elif sh.git('merge-base', '--is-ancestor',
                c2, c1, _ok_code=[0,1]).exit_code == 0:
        return 1
    else:
        return ts1 - ts2

def git_commit_eq(c1, c2):
    '''
        Compares two commits for equality, ignoring length and case
    '''
    clen = min(len(c1), len(c2))
    return c1.lower()[:clen] == c2.lower()[:clen]


@contextmanager
def chdir(path):
    orig_path = os.getcwd()
    os.chdir(path)
    yield
    os.chdir(orig_path)


def get_fname(root, fname):
    if exists(fname):
        return abspath(fname)
    
    fname = join(root, fname)
    if exists(fname):
        return abspath(fname)
    
    raise GSTError('%s does not exist' % fname)

def find_suggestions(cfg, fname):
    fname = splitext(basename(fname))[0].lower()
    fname = re.sub(r'[^a-z0-9]+', '', fname)
    
    for root, _, files in os.walk(cfg.upstream_root):
        for f in files:
            p = re.sub(r'[^a-z0-9]+', '', splitext(f)[0].lower())
            if p == fname:
                yield relpath(join(root, f), cfg.upstream_root)

def choose_suggestion(cfg, fname):
    suggestions = list(sorted(find_suggestions(cfg, fname)))
    if suggestions:
        print("Suggestions:")
        for i, s in enumerate(suggestions):
            print(" ", i, s)
        
        print("Select one or more files (specify multiple via comma)")
        inp = input("Use? [0-%s,n] (multi via comma) " % i)
        if inp != 'n':
            return sorted([suggestions[int(v)] for v in inp.split(',')]) 

class ValidationInfo:
    
    @staticmethod
    def from_line(cfg, dst_fname, line):
        line = line.strip()
        if line.startswith('# novalidate') or line.startswith('# notrack'):
            return ValidationInfo(notrack=True)
        
        s = line.split()
        if len(s) < 6:
            raise GSTError("Invalid validation line: %s" % line)
        
        return ValidationInfo(date=s[2],
                              initials=s[3],
                              hash=s[4],
                              orig_fnames=s[5:],
                              dst_fname=dst_fname,
                              cfg=cfg)
    
    @staticmethod
    def from_now(cfg, initials, orig_fnames):
        v = ValidationInfo(date=time.strftime('%Y-%m-%d'),
                           initials=initials,
                           orig_fnames=orig_fnames,
                           cfg=cfg)
        
        v.hash = v.orig_hash
        return v
    
    def __init__(self, **kwargs):
        self.notrack = kwargs.get('notrack', False)
        self.date = kwargs.get('date')
        self.initials = kwargs.get('initials')
        self.hash = kwargs.get('hash')
        self.orig_fnames = [posixpath.normpath(of) for of in kwargs.get('orig_fnames', [])]
        self.dst_fname = kwargs.get('dst_fname')
        self.cfg = kwargs.get('cfg')
    
    def is_up_to_date(self):
        return git_commit_eq(self.orig_hash, self.hash)
    
    @property
    def orig_hash(self):
        '''Returns or calculates the hash that we're tracking'''
        
        if not hasattr(self, '_orig_hash'):
            with chdir(self.cfg.upstream_root):
                hashes = []
                for fpath in self.orig_fnames:
                    # if one doesn't exist, everything is lost
                    if not exists(fpath):
                        hashes = []
                        break
                    # Return the first commit that isn't excluded
                    for commit in sh.git('log', '--follow', '--pretty=%ct %H', fpath, _tty_out=False, _iter=True):
                        ts, commit = commit.strip().split()
                        commit = commit[:short_hash_sz]
                        if (self.hash is not None and git_commit_eq(commit, self.hash)) or \
                           not self.cfg.is_commit_excluded(commit):
                            hashes.append((ts, commit))
                            break
                            
                if not hashes:
                    self._orig_hash = invalid_hash
                elif len(hashes) == 1:
                    self._orig_hash = hashes[0][1]
                else:
                    hashes.sort(key=cmp_to_key(git_commit_cmp))
                    
                    # Select the newest hash from the potentials
                    self._orig_hash = hashes[-1][1]
        
        return self._orig_hash
    
    @property
    def line(self):
        if self.notrack:
            return '# notrack\n'
        else:
            l = '# validated: %(date)s %(initials)s %(hash)s ' % self.__dict__
            l += ' '.join(self.orig_fnames) + '\n'
            return l
    
    def __repr__(self):
        return '<ValidationInfo: %s>' % self.line.strip()

# modify a single file
def set_info(fname, info):
    '''
        Writes the magic to the first line that starts with # validated
        or # notrack. If no such line exists, write to the first line
        of the file
    '''
    
    with open(fname, 'r') as fin, \
         tempfile.NamedTemporaryFile(dir=dirname(fname), mode='w', delete=False) as fout:
        
        found = False
        written = False
        
        # search for the line first
        for line in fin:
            if line.startswith('# validated') or \
               line.startswith('# novalidate') or \
               line.startswith('# notrack'):
                found = True
                break
        
        fin.seek(0)
        
        # Now rewrite the file
        for line in fin:
            if not written:
                if not found:
                    fout.write(info.line)
                    written = True
                    
                elif line.startswith('# validated') or \
                   line.startswith('# novalidate') or \
                   line.startswith('# notrack'):
                    line = info.line
                    written = True
            
            fout.write(line)
            
    file_replace(fout.name, fname)

def get_info(cfg, fname):
    with open(normpath(fname)) as fp:
        for line in fp:
            if line.startswith('# validated') or \
               line.startswith('# novalidate') or \
               line.startswith('# notrack'):
                return ValidationInfo.from_line(cfg, fname, line)

#
# Actions
#

def action_show(cfg, args):
    '''
        Show status of all files
    '''
    
    counts = {'good': 0, 'outdated': 0, 'unknown': 0, 'error': 0}
    
    if hasattr(args, 'filename') and args.filename is not None:
        _action_show(cfg, get_fname(cfg.validation_root, args.filename), counts)
    else:
        for root, _, files in os.walk(cfg.validation_root):
            for f in sorted(files):
                if not f.endswith('.py') or f == '__init__.py':
                    continue
                
                fname = join(root, f)
                _action_show(cfg, fname, counts)
    
    print()
    print("%(good)s OK, %(outdated)s out of date, %(unknown)s unknown, %(error)s error" % (counts))

def _action_show(cfg, fname, counts):
    path = relpath(fname, cfg.validation_root)
    extra = None

    try:
        info = get_info(cfg, fname)
    except GSTError as e:
        status = 'ERR'
        extra = str(e)
        counts['error'] += 1
    else:
        if info is None:
            status = '-- '
            counts['unknown'] += 1
        elif info.notrack:
            status = 'OK '
            counts['good'] += 1
        else:
            if info.is_up_to_date():
                status = 'OK '
                counts['good'] += 1
            elif info.orig_hash == invalid_hash:
                status = 'ERR'
                # TODO: create a better error message
                counts['unknown'] += 1
            else:
                status = "OLD"
                path += ' (%s..%s)' % (info.hash, info.orig_hash)
                counts['outdated'] += 1
    
    print('%s: %s' % (status, path))
    if extra:
        print('--> ', extra)
    

def action_diff(cfg, args):
    '''Shows diff of file since last validation'''
    
    info = get_info(cfg, get_fname(cfg.validation_root, args.filename))
    if info is None:
        raise GSTError("No validation information found for %s" % args.filename)
    
    if info.orig_hash == invalid_hash:
        update_src(cfg, info)
    
    with chdir(cfg.upstream_root): 
        git_log(cfg, info.orig_fnames,
                '%s..%s' % (info.hash, info.orig_hash))
    
    if not info.is_up_to_date():
        print()
        if input("Validate file? [y/n]").lower() in ['y', 'yes']:
            args.orig_fnames = None
            action_validate(cfg, args)
        

def action_validate(cfg, args):
    '''Sets validation metadata in specified file'''

    fname = get_fname(cfg.validation_root, args.filename)

    initials = args.initials
    if not initials:
        name = sh.git('config', 'user.name', _tty_out=False).strip()
        initials = ''.join(n[0] for n in name.split())
        
    if not initials:
        raise GSTError("Specify --initials or execute 'git config user.name Something'")
    
    orig_fnames = args.orig_fnames
    if not orig_fnames:
        info = get_info(cfg, fname)
        if info is not None:
            orig_fnames = info.orig_fnames
    
    # if there's no orig_filename specified, then raise an error
    if not orig_fnames:
        orig_fnames = choose_suggestion(cfg, fname)
        if not orig_fnames:
            raise GSTError("Error: must specify upstream filename(s)")
    
    info = ValidationInfo.from_now(cfg, initials, orig_fnames)
    
    # write the information to the file
    set_info(fname, info)
    
    print(fname)
    #print(join(cfg.upstream_root, orig_fname))
    print(info.line)
    
def action_notrack(cfg, args):
    '''Sets special notrack metadata in file'''
    fname = get_fname(cfg.validation_root, args.filename)
    info = ValidationInfo(notrack=True, cfg=cfg)
    set_info(fname, info)
    
    print(fname)
    print(info.line)


def action_show_log(cfg, args):
    '''Shows logs of file in upstream root'''
    fname = choose_suggestion(cfg, args.filename)
    if fname:
        with chdir(cfg.upstream_root):
            git_log(cfg, fname)

def update_src(cfg, info):
    print(info.orig_fnames, "no longer exists, choose another?")
    info.orig_fnames = choose_suggestion(cfg, relpath(info.dst_fname, cfg.validation_root))
    if info.orig_fnames:
        set_info(info.dst_fname, info)
        if hasattr(info, '_orig_hash'):
            delattr(info, '_orig_hash')

def action_update_src(cfg, args):
    '''Update the source of a file if it's renamed'''
    fname = get_fname(cfg.validation_root, args.filename)
    info = get_info(cfg, fname)
    if info is None:
        print(fname, "not validated, no source to update")
    elif info.orig_hash != invalid_hash:
        print("Update not required for", fname)
    else:
        update_src(cfg, info)

def action_upstream_checkout(cfg, args):
    '''Set upstream git repo to commit specified in config'''
    with chdir(cfg.upstream_root):
        os.system('git checkout %s' % cfg.upstream_commit)

    print("Upstream commit is now", cfg.upstream_commit)

def action_upstream_pull(cfg, args):
    '''Update upstream git repo and set commit in config'''
    with chdir(cfg.upstream_root):
        # TODO: this should be configurable
        os.system('git pull origin master')
    
    action_upstream_track(cfg, args)    

def action_upstream_track(cfg, args):
    '''Set upstream_commit to be whatever commit upstream happens to be at'''
    cfg.upstream_commit = cfg.get_upstream_head()
    cfg.save()
    
    print("Upstream commit changed to", cfg.upstream_commit)

#def action_upstream_clone(cfg, args):
#    pass



class GSTError(Exception):
    pass

class RepoData:
    '''
        Data is stored in an ini file called .gittrack::
        
            [git-source-track]
            
            # Upstream files
            upstream_root = ../path/to/files
            
            # Commit in upstream repository
            upstream_commit = xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
            
            # Files that are being validated 
            validation_root = path/to_files
            
            # Commits to exclude from git log output
            exclude_commits_file = foo/exclude_commits.txt
    
    '''
    
    def __init__(self, cfgpath):
        
        self.exclude_commits_file = None
        self._exclude_commits = None
        
        if not exists(cfgpath):
            raise GSTError("Configuration file '%s' was not found" % cfgpath)
        
        self.cfgpath = cfgpath
        
        self.cfg = cfg = RawConfigParser()
        cfg.read(cfgpath)
        
        cfgdir = dirname(cfgpath)
        
        # Backwards compat
        try:
            try:
                original_root = cfg.get(cfg_section, 'original_root')
                cfg.set(cfg_section, 'upstream_root', original_root)
            except NoOptionError:
                pass
            
            # All loaded paths are relative to the config file
            for k in ['upstream_root', 'validation_root', 'exclude_commits_file']:
                try:
                    path = cfg.get(cfg_section, k)
                except NoOptionError as e:
                    if k != 'exclude_commits_file':
                        raise GSTError("%s: %s" % (cfgpath, str(e)))
                else:
                    path = abspath(join(cfgdir, os.path.normpath(path)))
                    setattr(self, k, path)
            
            try:
                self.upstream_commit = cfg.get(cfg_section, 'upstream_commit')
            except (NoSectionError, KeyError):
                self.upstream_commit = None
                
            if not self.upstream_commit:
                print("Warning: no upstream_commit option set", file=sys.stderr)
                
        except NoSectionError as e:
            raise GSTError("%s: %s" % (cfgpath, str(e)))
        
    @property
    def excluded_commits(self):
        
        if self._exclude_commits is None:
            self._exclude_commits = []
            
            if self.exclude_commits_file and exists(self.exclude_commits_file):
                with open(self.exclude_commits_file) as fp:
                    for line in fp:
                        line = line.split()
                        if line:
                            self._exclude_commits.append(line[0].strip())
                        
        return self._exclude_commits
    
    def is_commit_excluded(self, commit):
        # ugh
        for e in self.excluded_commits:
            if git_commit_eq(e, commit):
                return True
        
        return False
    
    def save(self):
        with open(self.cfgpath, 'w') as fp:
            self.cfg.remove_option(cfg_section, 'original_root')
            self.cfg.set(cfg_section, 'upstream_commit', self.upstream_commit)
            
            self.cfg.write(fp)
        
    def get_upstream_head(self):
        with chdir(self.upstream_root):
            return sh.git('rev-parse', 'HEAD').strip()
    
def find_config_file():
    
    root = os.getcwd()
    repo_root = sh.git('rev-parse', '--show-toplevel').strip()
    
    while root:
        cfg_path = join(root, '.gittrack')
        if exists(cfg_path):
            return cfg_path
        
        elif repo_root == root:
            break
        else:
            root = split(root)[0]
    
def main():
    '''
        This tool allows one to put metadata in each file noting the last git
        commit that the upstream file was inspected at. Using this metadata,
        you can use the 'diff' subcommand to easily see the changes that were
        made to the upstream file.
    
        Once you're satisified that the destination version of the file matches
        sufficiently enough, use the set-valid command to record the validation
        data.
    '''
    
    parser = argparse.ArgumentParser(description=inspect.getdoc(main))
    subparsers = parser.add_subparsers(dest='action')
    
    sp = subparsers.add_parser('diff',
                               help=inspect.getdoc(action_diff))
    sp.add_argument('filename')
    sp.add_argument('--initials', default=None)
    
    sp = subparsers.add_parser('show',
                               help=inspect.getdoc(action_show))
    sp.add_argument('filename', nargs='?')
    
    sp = subparsers.add_parser('set-valid',
                               help=inspect.getdoc(action_validate))
    sp.add_argument('filename')
    sp.add_argument('orig_fnames', nargs='*')
    sp.add_argument('--initials', default=None)
    
    sp = subparsers.add_parser('set-notrack',
                               help=inspect.getdoc(action_notrack))
    sp.add_argument('filename')
    
    sp = subparsers.add_parser('show-log',
                               help=inspect.getdoc(action_show_log))
    sp.add_argument('filename')
    
    sp = subparsers.add_parser('update-src',
                               help=inspect.getdoc(action_update_src))
    sp.add_argument('filename')
    
    sp = subparsers.add_parser('upstream-checkout',
                               help=inspect.getdoc(action_upstream_checkout))
    
    sp = subparsers.add_parser('upstream-pull',
                               help=inspect.getdoc(action_upstream_pull))
    
    sp = subparsers.add_parser('upstream-track',
                               help=inspect.getdoc(action_upstream_track))
    
    sp = subparsers.add_parser('help', help='Show help (--help does not work as a git subcommand)')

    args = parser.parse_args()
    
    # Find the config file
    cfg_path = find_config_file()
    if not cfg_path:
        parser.error("Could not find .gittrack")
    
    action = args.action
    
    try:
        cfg = RepoData(cfg_path)
        
        if not exists(cfg.upstream_root):
            extra = ''
            if action == 'upstream-checkout':
                extra = ' (you may need to git pull manually)'
            raise GSTError("Upstream directory %s does not exist%s" % (cfg.upstream_root, extra))
        
        if cfg.upstream_commit and \
            (not action or not (action == 'help' or action.startswith('upstream-'))):
            upstream_head = cfg.get_upstream_head()
                
            if not git_commit_eq(upstream_head, cfg.upstream_commit):
                err = inspect.cleandoc('''
                    Upstream commit is %s, %s is in .gittrack
                    
                    To fix use one of these commands:
                    
                    * git source-track upstream-checkout: will set the upstream commit to match
                      that which is in .gittrack
                    * git source-track upstream-track: will modify .gittrack to match the current
                      upstream commit
                    
                    If in doubt, you probably want 'git source-track upstream-checkout'
                ''') % (upstream_head, cfg.upstream_commit)
                
                raise GSTError(err)
    except GSTError as e:
        print('Error:', str(e), file=sys.stderr)
        exit(1)
    
    try:
        if args.action == 'help':
            parser.print_help()
        
        elif args.action in [None, 'show']:
            action_show(cfg, args)
            
        elif args.action == 'diff':
            action_diff(cfg, args)
            
        elif args.action == 'set-valid':
            action_validate(cfg, args)
            
        elif args.action == 'set-notrack':
            action_notrack(cfg, args)
            
        elif args.action == 'show-log':
            action_show_log(cfg, args)
            
        elif args.action == 'update-src':
            action_update_src(cfg, args)
        
        elif args.action == 'upstream-checkout':
            action_upstream_checkout(cfg, args)
            
        elif args.action == 'upstream-pull':
            action_upstream_pull(cfg, args)
            
        elif args.action == 'upstream-track':
            action_upstream_track(cfg, args)
        
        else:
            parser.error("Invalid action %s" % args.action)
    except GSTError as e:
        print(str(e), file=sys.stderr)
        exit(1) 

if __name__ == '__main__':
    main()
