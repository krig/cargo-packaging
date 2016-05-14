import re


SV_RANGE = re.compile(r'^(?P<op>(?:\<=|\>=|=|\<|\>|\^|\~))?\s*'
                      r'(?P<major>(?:\*|0|[1-9][0-9]*))'
                      r'(\.(?P<minor>(?:\*|0|[1-9][0-9]*)))?'
                      r'(\.(?P<patch>(?:\*|0|[1-9][0-9]*)))?'
                      r'(\-(?P<prerelease>[0-9A-Za-z-]+(\.[0-9A-Za-z-]+)*))?'
                      r'(\+(?P<build>[0-9A-Za-z-]+(\.[0-9A-Za-z-]+)*))?$')
SEMVER = re.compile(r'^\s*(?P<major>(?:0|[1-9][0-9]*))'
                    r'(\.(?P<minor>(?:0|[1-9][0-9]*)))?'
                    r'(\.(?P<patch>(?:0|[1-9][0-9]*)))?'
                    r'(\-(?P<prerelease>[0-9A-Za-z-]+(\.[0-9A-Za-z-]+)*))?'
                    r'(\+(?P<build>[0-9A-Za-z-]+(\.[0-9A-Za-z-]+)*))?$')


class PreRelease(object):

    def __init__(self, pr):
        self._container = []
        if pr is not None:
            self._container += str(pr).split('.')

    def __str__(self):
        return '.'.join(self._container)

    def __repr__(self):
        return self._container

    def __getitem__(self, key):
        return self._container[key]

    def __len__(self):
        return len(self._container)

    def __gt__(self, rhs):
        return not ((self < rhs) or (self == rhs))

    def __ge__(self, rhs):
        return not (self < rhs)

    def __le__(self, rhs):
        return not (self > rhs)

    def __eq__(self, rhs):
        return self._container == rhs._container

    def __ne__(self, rhs):
        return not (self == rhs)

    def __lt__(self, rhs):
        if self == rhs:
            return False

        # not having a pre-release is higher precedence
        if len(self) == 0:
            if len(rhs) == 0:
                return False
            else:
                # 1.0.0 > 1.0.0-alpha
                return False
        else:
            if len(rhs) is None:
                # 1.0.0-alpha < 1.0.0
                return True

        # if both have one, then longer pre-releases are higher precedence
        if len(self) > len(rhs):
            # 1.0.0-alpha.1 > 1.0.0-alpha
            return False
        elif len(self) < len(rhs):
            # 1.0.0-alpha < 1.0.0-alpha.1
            return True

        # if both have the same length pre-release, must check each piece
        # numeric sub-parts have lower precedence than non-numeric sub-parts
        # non-numeric sub-parts are compared lexically in ASCII sort order
        for l, r in zip(self, rhs):
            if l.isdigit():
                if r.isdigit():
                    if int(l) < int(r):
                        # 2 > 1
                        return True
                    elif int(l) > int(r):
                        # 1 < 2
                        return False
                    else:
                        # 1 == 1
                        continue
                else:
                    # 1 < 'foo'
                    return True
            else:
                if r.isdigit():
                    # 'foo' > 1
                    return False

            # both are non-numeric
            if l < r:
                return True
            elif l > r:
                return False

        raise RuntimeError('PreRelease __lt__ failed')


class Semver(dict):

    def __init__(self, sv):
        match = SEMVER.match(str(sv))
        if match is None:
            raise ValueError('%s is not a valid semver string' % sv)

        self._input = sv
        self.update(match.groupdict())
        self.prerelease = PreRelease(self['prerelease'])

    def __str__(self):
        major, minor, patch, prerelease, build = self.parts_raw()
        s = ''
        if major is None:
            s += '0'
        else:
            s += major
        s += '.'
        if minor is None:
            s += '0'
        else:
            s += minor
        s += '.'
        if patch is None:
            s += '0'
        else:
            s += patch
        if len(self.prerelease):
            s += '-' + str(self.prerelease)
        if build is not None:
            s += '+' + build
        return s

    def __hash__(self):
        return hash(str(self))

    def as_range(self):
        return SemverRange('=%s' % self)

    def parts(self):
        major, minor, patch, prerelease, build = self.parts_raw()
        if major is None:
            major = '0'
        if minor is None:
            minor = '0'
        if patch is None:
            patch = '0'
        return (int(major), int(minor), int(patch), prerelease, build)

    def parts_raw(self):
        return (self['major'], self['minor'], self['patch'], self['prerelease'], self['build'])

    def __lt__(self, rhs):
        lmaj, lmin, lpat, lpre, _ = self.parts()
        rmaj, rmin, rpat, rpre, _ = rhs.parts()
        if lmaj < rmaj:
            return True
        if lmaj > rmaj:
            return False
        if lmin < rmin:
            return True
        if lmin > rmin:
            return False
        if lpat < rpat:
            return True
        if lpat > rpat:
            return False
        if lpre is not None and rpre is None:
            return True
        if lpre is not None and rpre is not None:
            if self.prerelease < rhs.prerelease:
                return True
        return False

    def __le__(self, rhs):
        return not (self > rhs)

    def __gt__(self, rhs):
        return not ((self < rhs) or (self == rhs))

    def __ge__(self, rhs):
        return not (self < rhs)

    def __eq__(self, rhs):
        # build metadata is only considered for equality
        lmaj, lmin, lpat, lpre, lbld = self.parts()
        rmaj, rmin, rpat, rpre, rbld = rhs.parts()
        return lmaj == rmaj and lmin == rmin and lpat == rpat and lpre == rpre and lbld == rbld

    def __ne__(self, rhs):
        return not (self == rhs)


class SemverRange(object):

    def __init__(self, sv):
        self._input = sv
        self._lower = None
        self._upper = None
        self._op = None
        self._semver = None

        sv = str(sv)
        svs = [x.strip() for x in sv.split(',')]

        if len(svs) > 1:
            self._op = '^'
            for sr in svs:
                rang = SemverRange(sr)
                if rang.lower() is not None:
                    if self._lower is None or rang.lower() < self._lower:
                        self._lower = rang.lower()
                if rang.upper() is not None:
                    if self._upper is None or rang.upper() > self._upper:
                        self._upper = rang.upper()
                op, semver = rang.op_semver()
                if semver is not None:
                    if op == '>=':
                        if self._lower is None or semver < self._lower:
                            self._lower = semver
                    if op == '<':
                        if self._upper is None or semver > self._upper:
                            self._upper = semver
            return

        match = SV_RANGE.match(sv)
        if match is None:
            raise ValueError('%s is not a valid semver range string' % sv)

        svm = match.groupdict()
        op, major, minor, patch, prerelease = svm['op'], svm['major'], svm['minor'], svm['patch'], svm['prerelease']
        prerelease = PreRelease(prerelease)

        # fix up the op
        if op is None:
            if major == '*' or minor == '*' or patch == '*':
                op = '*'
            else:
                # if no op was specified and there are no wildcards, then op
                # defaults to '^'
                op = '^'
        else:
            self._semver = Semver(sv[len(op):])

        if op not in ('<=', '>=', '<', '>', '=', '^', '~', '*'):
            raise ValueError('%s is not a valid semver operator' % op)

        self._op = op

        # lower bound
        def find_lower():
            if op in ('<=', '<', '=', '>', '>='):
                return None

            if op == '*':
                # wildcards specify a range
                if major == '*':
                    return Semver('0.0.0')
                elif minor == '*':
                    return Semver(major + '.0.0')
                elif patch == '*':
                    return Semver(major + '.' + minor + '.0')
            elif op == '^':
                # caret specifies a range
                if patch is None:
                    if minor is None:
                        # ^0 means >=0.0.0 and <1.0.0
                        return Semver(major + '.0.0')
                    else:
                        # ^0.0 means >=0.0.0 and <0.1.0
                        return Semver(major + '.' + minor + '.0')
                else:
                    # ^0.0.1 means >=0.0.1 and <0.0.2
                    # ^0.1.2 means >=0.1.2 and <0.2.0
                    # ^1.2.3 means >=1.2.3 and <2.0.0
                    if int(major) == 0:
                        if int(minor) == 0:
                            # ^0.0.1
                            return Semver('0.0.' + patch)
                        else:
                            # ^0.1.2
                            return Semver('0.' + minor + '.' + patch)
                    else:
                        # ^1.2.3
                        return Semver(major + '.' + minor + '.' + patch)
            elif op == '~':
                # tilde specifies a minimal range
                if patch is None:
                    if minor is None:
                        # ~0 means >=0.0.0 and <1.0.0
                        return Semver(major + '.0.0')
                    else:
                        # ~0.0 means >=0.0.0 and <0.1.0
                        return Semver(major + '.' + minor + '.0')
                else:
                    # ~0.0.1 means >=0.0.1 and <0.1.0
                    # ~0.1.2 means >=0.1.2 and <0.2.0
                    # ~1.2.3 means >=1.2.3 and <1.3.0
                    return Semver(major + '.' + minor + '.' + patch)

            raise RuntimeError('No lower bound')
        self._lower = find_lower()

        def find_upper():
            if op in ('<=', '<', '=', '>', '>='):
                return None

            if op == '*':
                # wildcards specify a range
                if major == '*':
                    return None
                elif minor == '*':
                    return Semver(str(int(major) + 1) + '.0.0')
                elif patch == '*':
                    return Semver(major + '.' + str(int(minor) + 1) + '.0')
            elif op == '^':
                # caret specifies a range
                if patch is None:
                    if minor is None:
                        # ^0 means >=0.0.0 and <1.0.0
                        return Semver(str(int(major) + 1) + '.0.0')
                    else:
                        # ^0.0 means >=0.0.0 and <0.1.0
                        return Semver(major + '.' + str(int(minor) + 1) + '.0')
                else:
                    # ^0.0.1 means >=0.0.1 and <0.0.2
                    # ^0.1.2 means >=0.1.2 and <0.2.0
                    # ^1.2.3 means >=1.2.3 and <2.0.0
                    if int(major) == 0:
                        if int(minor) == 0:
                            # ^0.0.1
                            return Semver('0.0.' + str(int(patch) + 1))
                        else:
                            # ^0.1.2
                            return Semver('0.' + str(int(minor) + 1) + '.0')
                    else:
                        # ^1.2.3
                        return Semver(str(int(major) + 1) + '.0.0')
            elif op == '~':
                # tilde specifies a minimal range
                if patch is None:
                    if minor is None:
                        # ~0 means >=0.0.0 and <1.0.0
                        return Semver(str(int(major) + 1) + '.0.0')
                    else:
                        # ~0.0 means >=0.0.0 and <0.1.0
                        return Semver(major + '.' + str(int(minor) + 1) + '.0')
                else:
                    # ~0.0.1 means >=0.0.1 and <0.1.0
                    # ~0.1.2 means >=0.1.2 and <0.2.0
                    # ~1.2.3 means >=1.2.3 and <1.3.0
                    return Semver(major + '.' + str(int(minor) + 1) + '.0')

            raise RuntimeError('No upper bound')
        self._upper = find_upper()

    def __repr__(self):
        return "SemverRange(%s, op=%s, semver=%s, lower=%s, upper=%s)" % (repr(self._input), self._op, self._semver, self._lower, self._upper)

    def __str__(self):
        return self._input

    def lower(self):
        return self._lower

    def upper(self):
        return self._upper

    def op_semver(self):
        return self._op, self._semver

    def compare(self, sv):
        if not isinstance(sv, Semver):
            sv = Semver(sv)

        op = self._op
        if op == '*':
            if self._semver is not None and self._semver['major'] == '*':
                return sv >= Semver('0.0.0')
            if self._lower is not None and sv < self._lower:
                return False
            if self._upper is not None and sv >= self._upper:
                return False
            return True
        elif op == '^':
            return (sv >= self._lower) and (sv < self._upper)
        elif op == '~':
            return (sv >= self._lower) and (sv < self._upper)
        elif op == '<=':
            return sv <= self._semver
        elif op == '>=':
            return sv >= self._semver
        elif op == '<':
            return sv < self._semver
        elif op == '>':
            return sv > self._semver
        elif op == '=':
            return sv == self._semver

        raise RuntimeError('Semver comparison failed to find a matching op')


def test_semver():
    """
    Tests for Semver parsing. Run using py.test: py.test bootstrap.py
    """
    assert str(Semver("1")) == "1.0.0"
    assert str(Semver("1.1")) == "1.1.0"
    assert str(Semver("1.1.1")) == "1.1.1"
    assert str(Semver("1.1.1-alpha")) == "1.1.1-alpha"
    assert str(Semver("1.1.1-alpha.1")) == "1.1.1-alpha.1"
    assert str(Semver("1.1.1-alpha+beta")) == "1.1.1-alpha+beta"
    assert str(Semver("1.1.1-alpha+beta.1")) == "1.1.1-alpha+beta.1"


def test_semver_eq():
    assert Semver("1") == Semver("1.0.0")
    assert Semver("1.1") == Semver("1.1.0")
    assert Semver("1.1.1") == Semver("1.1.1")
    assert Semver("1.1.1-alpha") == Semver("1.1.1-alpha")
    assert Semver("1.1.1-alpha.1") == Semver("1.1.1-alpha.1")
    assert Semver("1.1.1-alpha+beta") == Semver("1.1.1-alpha+beta")
    assert Semver("1.1.1-alpha.1+beta") == Semver("1.1.1-alpha.1+beta")
    assert Semver("1.1.1-alpha.1+beta.1") == Semver("1.1.1-alpha.1+beta.1")


def test_semver_comparison():
    assert Semver("1") < Semver("2.0.0")
    assert Semver("1.1") < Semver("1.2.0")
    assert Semver("1.1.1") < Semver("1.1.2")
    assert Semver("1.1.1-alpha") < Semver("1.1.1")
    assert Semver("1.1.1-alpha") < Semver("1.1.1-beta")
    assert Semver("1.1.1-alpha") < Semver("1.1.1-beta")
    assert Semver("1.1.1-alpha") < Semver("1.1.1-alpha.1")
    assert Semver("1.1.1-alpha.1") < Semver("1.1.1-alpha.2")
    assert Semver("1.1.1-alpha+beta") < Semver("1.1.1+beta")
    assert Semver("1.1.1-alpha+beta") < Semver("1.1.1-beta+beta")
    assert Semver("1.1.1-alpha+beta") < Semver("1.1.1-beta+beta")
    assert Semver("1.1.1-alpha+beta") < Semver("1.1.1-alpha.1+beta")
    assert Semver("1.1.1-alpha.1+beta") < Semver("1.1.1-alpha.2+beta")
    assert Semver("0.5") < Semver("2.0")
    assert not (Semver("2.0") < Semver("0.5"))
    assert not (Semver("0.5") > Semver("2.0"))
    assert not (Semver("0.5") >= Semver("2.0"))
    assert Semver("2.0") >= Semver("0.5")
    assert Semver("2.0") > Semver("0.5")
    assert not (Semver("2.0") > Semver("2.0"))
    assert not (Semver("2.0") < Semver("2.0"))


def test_semver_range():
    def bounds(spec, lowe, high):
        lowe = Semver(lowe) if lowe is not None else lowe
        high = Semver(high) if high is not None else high
        assert SemverRange(spec).lower() == lowe and SemverRange(spec).upper() == high
    bounds('0',      '0.0.0', '1.0.0')
    bounds('0.0',    '0.0.0', '0.1.0')
    bounds('0.0.0',  '0.0.0', '0.0.1')
    bounds('0.0.1',  '0.0.1', '0.0.2')
    bounds('0.1.1',  '0.1.1', '0.2.0')
    bounds('1.1.1',  '1.1.1', '2.0.0')
    bounds('^0',     '0.0.0', '1.0.0')
    bounds('^0.0',   '0.0.0', '0.1.0')
    bounds('^0.0.0', '0.0.0', '0.0.1')
    bounds('^0.0.1', '0.0.1', '0.0.2')
    bounds('^0.1.1', '0.1.1', '0.2.0')
    bounds('^1.1.1', '1.1.1', '2.0.0')
    bounds('~0',     '0.0.0', '1.0.0')
    bounds('~0.0',   '0.0.0', '0.1.0')
    bounds('~0.0.0', '0.0.0', '0.1.0')
    bounds('~0.0.1', '0.0.1', '0.1.0')
    bounds('~0.1.1', '0.1.1', '0.2.0')
    bounds('~1.1.1', '1.1.1', '1.2.0')
    bounds('*',      '0.0.0', None)
    bounds('0.*',    '0.0.0', '1.0.0')
    bounds('0.0.*',  '0.0.0', '0.1.0')


def test_semver_multirange():
    assert SemverRange(">= 0.5, < 2.0").compare("1.0.0")
    assert SemverRange("*").compare("0.2.7")
