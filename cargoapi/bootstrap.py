from __future__ import print_function
import os
import re
import sys
import subprocess
import tarfile
import pytoml as toml
from . import semver

BSCRIPT = re.compile(r'^cargo:(?P<key>([^\s=]+))(=(?P<value>.+))?$')
BNAME = re.compile('^(lib)?(?P<name>([^_]+))(_.*)?$')


class CrateInfo(object):
    def __init__(self, target, cdir, cfg):
        self.name = None
        self.version = None
        self.deps = []
        self.build = []
        self.features = []

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
                if 'version' not in v:
                    deps.append({'name': k, 'path': os.path.join(cdir, v['path']), 'local': True, 'req': 0})
                else:
                    opts = v.get('optional', False)
                    ftrs = v.get('features', [])
                    deps.append({'name': k, 'path': v['path'], 'req': v['version'], 'features': ftrs, 'optional': opts})
            else:
                opts = v.get('optional', False)
                ftrs = v.get('features', [])
                deps.append({'name': k, 'req': v['version'], 'features': ftrs, 'optional': opts})

        feats = cfg.get('features', None)
        if feats is not None:
            defaults = feats.get('default')
            if defaults:
                self.features.append('default')
                for df in defaults:
                    self.features.append(df)
                    if df in feats:
                        self.features.extend(feats[df])

        self.name = name
        self.version = ver
        self.deps = deps
        self.build = build


def crate_info_from_toml(target, cdir):
    if 'url-0.5.7' in cdir:
        url_057_toml = '''[package]

name = "url"
version = "0.5.7"
authors = [ "Simon Sapin <simon.sapin@exyr.org>" ]

description = "URL library for Rust, based on the WHATWG URL Standard"
documentation = "http://servo.github.io/rust-url/url/index.html"
repository = "https://github.com/servo/rust-url"
readme = "README.md"
keywords = ["url", "parser"]
license = "MIT/Apache-2.0"

[features]
query_encoding = ["encoding"]
serde_serialization = ["serde"]

[dependencies.encoding]
version = "0.2"
optional = true

[dependencies.serde]
version = ">=0.6.1, <0.8"
optional = true

[dependencies]
uuid = "0.1.17"
rustc-serialize = "0.3"
unicode-bidi = "0.2.3"
unicode-normalization = "0.1.2"
matches = "0.1"
'''
        cfg = toml.loads(url_057_toml)
    else:
        ctoml = open(os.path.join(cdir, 'Cargo.toml'), 'rb')
        cfg = toml.load(ctoml)
    return CrateInfo(target, cdir, cfg)

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
        for l in self.stdout:
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
    BLACKLIST = []
    OPTIONALS = []
    PACKAGES = []
    UNRESOLVED = []
    CRATES = {}
    BUILT = {}

    def __init__(self, crate, ver, cdir, build, dep_info):
        self._crate = crate
        self._version = ver
        self._dir = cdir
        self._dep_env = {}
        self._dep_info = dep_info
        self._builddeps = {}
        self._resolved = False
        # build buildscripts first, then libs, then bins
        self._build = [x for x in build if x.get('type') == 'build_script']
        self._build += [x for x in build if x.get('type') == 'lib']
        self._build += [x for x in build if x.get('type') == 'bin']
        self._env = {}
        self._extra_flags = []

        for lock in Crate.PACKAGES:
            if lock['name'] == crate and lock['version'] == ver:
                self._lock = lock
                break
        else:
            raise ValueError("No lock data for %s-%s" % (crate, ver))

        self._deps = []
        dstr = re.compile(r'(\S+)\s+(\S+)(?:\s+\((.+)\))?')
        for ldep in self._lock.get('dependencies', []):
            m = dstr.match(ldep)
            if not m:
                raise ValueError("Failed to parse dependency for %s: %s" % (crate, ldep))
            ldep_name = m.group(1)
            ldep_ver = m.group(2)
            for dep in dep_info:
                if dep['name'] != ldep_name:
                    continue
                req = semver.SemverRange(dep['req'])
                if req.compare(ldep_ver):
                    ndep = {'version': ldep_ver}
                    ndep.update(dep)
                    self._deps.append(ndep)

    def namever(self):
        return "%s-%s" % (self._crate, self._version)

    def unpack_crate(self, name, version):
        namever = '%s-%s' % (name, version)
        if os.path.isdir(os.path.join(Crate.CACHE, namever)):
            return os.path.join(Crate.CACHE, namever)
        else:
            cfp = os.path.join(Crate.CACHE, '%s.crate' % (namever))
            with tarfile.open(cfp) as tf:
                dbg('unpacking %s.crate to %s...' % (namever, Crate.CACHE))
                tf.extractall(path=Crate.CACHE)
            return os.path.join(Crate.CACHE, namever)
        return None

    def build_dep(self, namever, info, out_dir):
        print("Build", namever)
        crate = Crate.CRATES[namever]
        extern, env, extra_flags = crate.build(self.namever(), out_dir, info.get('features', []))
        self._dep_env[crate._crate] = env
        self._extra_flags += extra_flags
        return extern

    def resolve(self, target_dir):
        if self._resolved:
            return

        if self._dep_info is not None:
            dbg("Resolving dependencies for: %s" % (self.namever()))
            for d in self._deps:
                kind = d.get('kind', 'normal')
                if kind not in ('normal', 'build'):
                    dbg('Skipping %s dep %s' % (kind, d['name']))
                    continue

                deps = []
                name, version = d['name'], d['version']
                dbg('Looking up info for %s: %s' % (name, d))
                if not d.get('local', False):
                    cratedir = self.unpack_crate(name, version)
                    crateinfo = crate_info_from_toml(Crate.TARGET, cratedir)
                    name = crateinfo.name
                    deps += crateinfo.deps
                    build = crateinfo.build
                else:
                    cratedir = d['path']
                    crateinfo = crate_info_from_toml(Crate.TARGET, cratedir)
                    name = crateinfo.name
                    deps += crateinfo.deps
                    build = crateinfo.build

                features = crateinfo.features
                dbg('Features for %s: %s' % (name, features))

                optional = d.get('optional', False)
                if optional and d['name'] not in Crate.OPTIONALS and d['name'] not in features:
                    dbg('Skipping optional dep %s' % d['name'])
                    continue

                dcrate = Crate(name, version, cratedir, build, deps)
                if dcrate.namever() in Crate.CRATES:
                    dcrate = Crate.CRATES[dcrate.namever()]
                Crate.UNRESOLVED.append(dcrate)

                # clean up the list of features that are enabled
                tftrs = d.get('features', [])
                if isinstance(tftrs, dict):
                    tftrs = tftrs.keys()
                else:
                    tftrs = [x for x in tftrs if len(x) > 0]

                # add 'default' if default_features is true
                if d.get('default_features', True):
                    tftrs.append('default')

                # if isinstance(ftrs, dict):
                #     # add any available features that are activated by the
                #     # dependency entry in the parent's dependency record,
                #     # and any features they depend on recursively
                #     def add_features(f):
                #         if f in ftrs:
                #             for k in ftrs[f]:
                #                 # guard against infinite recursion
                #                 if k not in features:
                #                     features.append(k)
                #                     add_features(k)
                #     for k in tftrs:
                #         add_features(k)
                # else:
                #     features += [x for x in ftrs if (len(x) > 0) and (x in tftrs)]

                if dcrate is not None:
                    self.add_dep(dcrate, features)

        self._resolved = True
        Crate.CRATES[self.namever()] = self

    def add_dep(self, crate, features):
        namever = crate.namever()
        if namever in self._builddeps:
            return
        self._builddeps[namever] = {'features': [str(x) for x in features]}

    def build(self, by, out_dir, features=[]):
        output_name = flatdash(self._crate)
        extra_filename = '-%s' % (self._version.replace('.', '_'))
        output_name = os.path.join(out_dir, 'lib%s%s.rlib' % (flatdash(self._crate), extra_filename))
        if self.namever() in Crate.BUILT:
            return ({'name': self._crate, 'lib': output_name}, self._env, self._extra_flags)

        externs = []

        for dep, info in self._builddeps.iteritems():
            extern = self.build_dep(dep, info, out_dir)
            externs.append(extern)

        if os.path.isfile(output_name):
            print('Skipping %s, already built (needed by: %s)' % (self.namever(), str(by)))
            Crate.BUILT[self.namever()] = by
            return ({'name': self._crate, 'lib': output_name}, self._env, self._extra_flags)

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
        for l, e in self._dep_env.iteritems():
            for k, v in e.iteritems():
                if type(v) is not str and type(v) is not unicode:
                    v = str(v)
                env['DEP_%s_%s' % (l.upper(), v.upper())] = v
        # create the builders, build scripts are first
        cmds = []
        for b in self._build:
            v = str(self._version).replace('.', '_')
            cmd = ['rustc']
            #cmd.append(os.path.join(self._dir, b['path']))
            cmd.append(b['path'])
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
                nn = e['name'].replace('-', '_')
                ln = e['lib']
                # TODO: fix crate name / lib name confusion
                # (the extern name is the lib name, not the crate name)
                if nn == 'winapi_build':
                    nn = 'build'
                    ln = ln.replace('libwinapi_build', 'libbuild')
                cmd.append('%s=%s' % (nn, ln))

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

        dbg(self._build)
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

    target_dir = os.path.abspath(target_dir)
    crate_dir = os.path.abspath(crate_dir)
    rootdir = os.path.abspath('.')

    crateinfo = crate_info_from_toml(target, rootdir)
    name = crateinfo.name
    ver = crateinfo.version
    deps = crateinfo.deps
    build = crateinfo.build
    print("name:", name)
    print("version:", ver)

    lock_data = lock_info(rootdir)
    package_versions = lock_data['package']
    Crate.TARGET = target
    Crate.HOST = target
    Crate.CACHE = crate_dir
    Crate.BLACKLIST = blacklist
    Crate.OPTIONALS = optionals
    Crate.PACKAGES.append(lock_data['root'])
    Crate.PACKAGES.extend(package_versions)
    cargo_crate = Crate(name, ver, rootdir, build, deps)
    Crate.UNRESOLVED.append(cargo_crate)
    while len(Crate.UNRESOLVED) > 0:
        crate = Crate.UNRESOLVED.pop(0)
        crate.resolve(target_dir)
    cargo_crate.build('cargo2rpm', target_dir)
