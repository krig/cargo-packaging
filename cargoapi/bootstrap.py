from __future__ import print_function
import os
import re
import subprocess
import pytoml as toml
from . import semver

BSCRIPT = re.compile(r'^cargo:(?P<key>([^\s=]+))(=(?P<value>.+))?$')
BNAME = re.compile('^(lib)?(?P<name>([^_]+))(_.*)?$')


def crate_info_from_toml(target, cdir):
    try:
        with open(os.path.join(cdir, 'Cargo.toml'), 'rb') as ctoml:
            cfg = toml.load(ctoml)
            build = []
            p = cfg.get('package', cfg.get('project', {}))
            name = p.get('name', None)
            ver = p.get('version', None)
            if (name is None) or (ver is None):
                raise RuntimeError('invalid .toml file format')

            # look for a "links" item
            lnks = p.get('links', [])
            if type(lnks) is not list:
                lnks = [lnks]

            # look for a "build" item
            bf = p.get('build', None)

            # if we have a 'links', there must be a 'build'
            if len(lnks) > 0 and bf is None:
                raise RuntimeError('cargo requires a "build" item if "links" is specified')

            # there can be target specific build script overrides
            boverrides = {}
            for lnk in lnks:
                boverrides.update(cfg.get('target', {}).get(target, {}).get(lnk, {}))

            bmain = False
            if bf is not None:
                build.append({
                    'type': 'build_script',
                    'path': [bf],
                    'name': name.replace('-', '_'),
                    'links': lnks,
                    'overrides': boverrides
                })

            # look for libs array
            libs = cfg.get('lib', [])
            if type(libs) is not list:
                libs = [libs]
            for l in libs:
                l['type'] = 'lib'
                l['links'] = lnks
                if l.get('path', None) is None:
                    l['path'] = ['lib.rs']
                build.append(l)
                bmain = True

            # look for bins array
            bins = cfg.get('bin', [])
            if type(bins) is not list:
                bins = [bins]
            for b in bins:
                if b.get('path', None) is None:
                    b['path'] = [
                        os.path.join('bin', '%s.rs' % b['name']),
                        os.path.join('bin', 'main.rs'),
                        '%s.rs' % b['name'],
                        'main.rs'
                    ]
                build.append({
                    'type': 'bin',
                    'name': b['name'],
                    'path': b['path'],
                    'links': lnks
                })
                bmain = True

            # if no explicit directions on what to build, then add a default
            if not bmain:
                build.append({
                    'type': 'lib',
                    'path': 'lib.rs',
                    'name': name.replace('-', '_')
                })

            for b in build:
                # make sure the path is a list of possible paths
                if type(b['path']) is not list:
                    b['path'] = [b['path']]
                bin_paths = []
                for p in b['path']:
                    bin_paths.append(os.path.join(cdir, p))
                    bin_paths.append(os.path.join(cdir, 'src', p))

                found_path = None
                for p in bin_paths:
                    if os.path.isfile(p):
                        found_path = p
                        break

                if found_path is None:
                    raise RuntimeError('could not find %s to build in %s', (build, cdir))
                else:
                    b['path'] = found_path

            d = cfg.get('build-dependencies', {})
            d.update(cfg.get('dependencies', {}))
            d.update(cfg.get('target', {}).get(target, {}).get('dependencies', {}))
            deps = []
            for k, v in d.iteritems():
                if type(v) is not dict:
                    deps.append({'name': k, 'req': v})
                elif 'path' in v:
                    if v.get('version', None) is None:
                        deps.append({'name': k, 'path': os.path.join(cdir, v['path']), 'local': True, 'req': 0})
                    else:
                        opts = v.get('optional', False)
                        ftrs = v.get('features', [])
                        deps.append({'name': k, 'path': v['path'], 'req': v['version'], 'features': ftrs, 'optional': opts})
                else:
                    opts = v.get('optional', False)
                    ftrs = v.get('features', [])
                    deps.append({'name': k, 'req': v['version'], 'features': ftrs, 'optional': opts})

            return (name, ver, deps, build)

    except Exception, e:
        print('failed to load toml file for: %s (%s)' % (cdir, str(e)))

    return (None, None, [], 'lib.rs')


def lock_info(cdir):
    with open(os.path.join(cdir, 'Cargo.lock'), 'rb') as lockfile:
        lockf = toml.load(lockfile)
        return lockf


def flatdash(str):
    return str.replace('-', '_')


def dbg(str):
    print(str)


class Runner(object):
    def __init__(self, c, e, cwd=None):
        self._cmd = c
        if not isinstance(self._cmd, list):
            self._cmd = [self._cmd]
        self._env = e
        self.stdout = []
        self.stderr = []
        self.returncode = 0
        self.cwd = cwd

    def __call__(self, c, e):
        cmd = self._cmd + c
        env = dict(self._env, **e)
        envstr = ''
        for k, v in env.iteritems():
            envstr += ' %s="%s"' % (k, v)
        if self.cwd is not None:
            dbg('cd %s && %s %s' % (self.cwd, envstr, ' '.join(cmd)))
        else:
            dbg('%s %s' % (envstr, ' '.join(cmd)))

        proc = subprocess.Popen(cmd, env=env,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                cwd=self.cwd)
        out, err = proc.communicate()

        for lo in out.split('\n'):
            if len(lo) > 0:
                self.stdout.append(lo)

        for le in err.split('\n'):
            if len(le) > 0:
                self.stderr.append(le)
                dbg(le)

        self.returncode = proc.wait()
        return self.stdout


class RustcRunner(Runner):
    def __call__(self, c, e):
        super(RustcRunner, self).__call__(c, e)
        return ([], {}, {})


class BuildScriptRunner(Runner):
    def __call__(self, c, e):
        super(BuildScriptRunner, self).__call__(c, e)

        # parse the output for cargo: lines
        cmd = []
        env = {}
        denv = {}
        for l in self.output():
            match = BSCRIPT.match(str(l))
            if match is None:
                continue
            pieces = match.groupdict()
            k = pieces['key']
            v = pieces['value']

            if k == 'rustc-link-lib':
                cmd += ['-l', v]
            elif k == 'rustc-link-search':
                cmd += ['-L', v]
            elif k == 'rustc-cfg':
                cmd += ['--cfg', v]
                env['CARGO_FEATURE_%s' % v.upper().replace('-', '_')] = 1
            else:
                denv[k] = v
        return (cmd, env, denv)


class Crate(object):
    TARGET = None
    HOST = None
    CACHE = None
    PACKAGES = []
    UNRESOLVED = []
    BUILT = {}

    def __init__(self, crate, ver, cdir, build):
        self._crate = crate
        self._version = ver
        self._dir = cdir
        # build buildscripts first, then libs, then bins
        self._build = [x for x in build if x.get('type') == 'build_script']
        self._build += [x for x in build if x.get('type') == 'lib']
        self._build += [x for x in build if x.get('type') == 'bin']
        self._env = {}
        self._extra_flags = []

        for lock in Crate.PACKAGES:
            print(lock)
            if lock['name'] == crate and lock['version'] == ver:
                self._lock = lock
                break
        else:
            raise ValueError("No lock data for %s-%s" % (crate, ver))

    def namever(self):
        return "%s-%s" % (self._crate, self._version)

    def build(self, by, out_dir, features=[]):
        output_name = flatdash(self._crate)
        extra_filename = '-%s' % (flatdash(self._version))
        output_name = os.path.join(out_dir, 'lib%s%s.rlib' % (flatdash(self._crate), extra_filename))
        if self.namever() in Crate.BUILT:
            return ({'name': self._crate, 'lib': output_name}, self._env, self._extra_flags)

        if os.path.isfile(output_name):
            print('Skipping %s, already built (needed by: %s)' % (str(self), str(by)))
            Crate.BUILT[self.namever()] = by
            return ({'name': self._crate, 'lib': output_name}, self._env, self._extra_flags)

        externs = []
        extra_flags = []

        # build the environment for subcommands
        tenv = dict(os.environ)
        env = {}
        env['PATH'] = tenv['PATH']
        env['OUT_DIR'] = out_dir
        env['TARGET'] = Crate.TARGET
        env['HOST'] = Crate.HOST
        env['NUM_JOBS'] = '1'
        env['OPT_LEVEL'] = '0'
        env['DEBUG'] = '0'
        env['PROFILE'] = 'release'
        env['CARGO_MANIFEST_DIR'] = self._dir
        sv = semver.Semver(self._version)
        env['CARGO_PKG_VERSION_MAJOR'] = sv['major']
        env['CARGO_PKG_VERSION_MINOR'] = sv['minor']
        env['CARGO_PKG_VERSION_PATCH'] = sv['patch']
        env['CARGO_PKG_VERSION_PRE'] = sv['prerelease'] or ''
        env['CARGO_PKG_VERSION'] = self._version
        for f in features:
            env['CARGO_FEATURE_%s' % f.upper().replace('-', '_')] = '1'
        #for l, e in self._dep_env.iteritems():
        #    for k, v in e.iteritems():
        #        if type(v) is not str and type(v) is not unicode:
        #            v = str(v)
        #        env['DEP_%s_%s' % (l.upper(), v.upper())] = v
        # create the builders, build scrips are first
        cmds = []
        for b in self._build:
            v = str(self._version).replace('.', '_')
            cmd = ['rustc']
            cmd.append(os.path.join(self._dir, b['path']))
            cmd.append('--crate-name')
            if b['type'] == 'lib':
                b.setdefault('name', self._crate)
                cmd.append(b['name'].replace('-', '_'))
                cmd.append('--crate-type')
                cmd.append('lib')
            elif b['type'] == 'build_script':
                cmd.append('build_script_%s' % b['name'].replace('-', '_'))
                cmd.append('--crate-type')
                cmd.append('bin')
            else:
                cmd.append(b['name'].replace('-', '_'))
                cmd.append('--crate-type')
                cmd.append('bin')

            for f in features:
                cmd.append('--cfg')
                cmd.append('feature=\"%s\"' % f)

            cmd.append('-C')
            cmd.append('extra-filename=' + extra_filename)

            cmd.append('--out-dir')
            cmd.append('%s' % out_dir)
            cmd.append('--emit=dep-info,link')
            cmd.append('--target')
            cmd.append(Crate.TARGET)
            cmd.append('-L')
            cmd.append('%s' % out_dir)
            cmd.append('-L')
            cmd.append('%s/lib' % out_dir)

            # add in the flags from dependencies
            cmd += self._extra_flags

            for e in externs:
                cmd.append('--extern')
                cmd.append('%s=%s' % (e['name'].replace('-', '_'), e['lib']))

            # get the pkg key name
            match = BNAME.match(b['name'])
            if match is not None:
                match = match.groupdict()['name'].replace('-', '_')

            # queue up the runner
            cmds.append({'name': b['name'], 'env_key': match, 'cmd': RustcRunner(cmd, env)})

            # queue up the build script runner
            if b['type'] == 'build_script':
                bcmd = os.path.join(out_dir, 'build_script_%s-%s' % (b['name'], v))
                cmds.append({'name': b['name'], 'env_key': match, 'cmd': BuildScriptRunner(bcmd, env, self._dir)})

        dbg('Building %s (needed by: %s)' % (self.namever(), str(by)))

        bcmd = []
        benv = {}
        for c in cmds:
            runner = c['cmd']

            (c1, e1, e2) = runner(bcmd, benv)

            if runner.returncode != 0:
                raise RuntimeError('build command failed: %s\nOutput: %s' % (runner.returncode, runner.stdout))

            bcmd += c1
            benv = dict(benv, **e1)

            key = c['env_key']
            for k, v in e2.iteritems():
                self._env['DEP_%s_%s' % (key.upper(), k.upper())] = v

        Crate.BUILT[self.namever()] = str(by)
        return ({'name': self._crate, 'lib': output_name}, self._env, bcmd)



def build(target_dir, crate_dir, target, blacklist, optionals):
    print("target-dir:", target_dir)
    print("crate-dir:", crate_dir)
    print("target:", target)

    name, ver, deps, build = crate_info_from_toml(target, '.')
    print("name:", name)
    print("version:", ver)

    lock_data = lock_info('.')
    package_versions = lock_data['package']
    Crate.TARGET = target
    Crate.HOST = target
    Crate.CACHE = crate_dir
    Crate.PACKAGES.append(lock_data['root'])
    Crate.PACKAGES.extend(package_versions)

    cargo_crate = Crate(name, ver, '.', build)
    cargo_crate.build('cargo2rpm', target_dir)
