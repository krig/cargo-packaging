# cargoapi module
# tools for interacting with a local rust registry
# as well as fetching crates and metadata from crates.io

import os
import json
from dulwich import porcelain
import requests

_AUTHOR = "cargo-packager <packaging@opensuse.org>"
_COMMITTER = "cargo-packager <packaging@opensuse.org>"

_CRATES_API = "https://crates.io/api/v1/crates"
_INDEX_URL = "https://github.com/rust-lang/crates.io-index/tree/master"


def index_for_crate(root, crate):
    clen = len(crate)
    if clen == 1:
        return "/".join([root, "1", crate])
    elif clen == 2:
        return "/".join([root, "2", crate])
    elif clen == 3:
        return "/".join([root, "3", crate[0], crate])
    else:
        return "/".join([root, crate[0:2], crate[2:4], crate])


def update_crate(indexfile, name, version, entry):
    if os.path.isfile(indexfile):
        found = False
        newindex = []
        with open(indexfile, "r") as f:
            for line in f:
                e = json.loads(line)
                if e["vers"] == version:
                    newindex.append("%s\n" % (entry))
                    found = True
                else:
                    newindex.append(line)
            if not found:
                newindex.append("%s\n" % (entry))
        with open(indexfile, "w") as f:
            f.write("".join(newindex))
    else:
        with open(indexfile, "w") as f:
            f.write("%s\n" % (entry))


def remove_crate(indexfile, name, version):
    if os.path.isfile(indexfile):
        found = False
        newindex = []
        with open(indexfile, "r") as f:
            for line in f:
                e = json.loads(line)
                if e["vers"] == version:
                    found = True
                else:
                    newindex.append(line)
        if found:
            with open(indexfile, "w") as f:
                f.write("".join(newindex))


def commit(root, indexfile, message=None):
    with porcelain.open_repo_closing(root) as repo:
        porcelain.add(repo, indexfile)
        if message is None:
            message = "update %s" % (os.path.basename(indexfile))
        porcelain.commit(repo, message=message, author=_AUTHOR, committer=_COMMITTER)


def fetch_index_entry(name):
    """
    Index entry downloader
    Fetches the json data for the crate from crates.io-index on github
    """
    url = index_for_crate(_INDEX_URL, name)
    r = requests.get(url)
    r.raise_for_status()
    return r.content


def fetch_crate_metadata(name):
    """
    Metadata downloader
    Generates metadata objects, one for each available version
    """
    url = "/".join([_CRATES_API, name])
    r = requests.get(url)
    r.raise_for_status()
    return r.json()


def crate_source_url(name, version):
    """
    Return the url of the crate
    """
    url = "/".join([_CRATES_API, name, version, "download"])
    r = requests.get(url, stream=True)
    return r.url


def download_crate(name, version):
    """
    Download the crate tarball
    """
    url = "/".join([_CRATES_API, name, version, "download"])
    r = requests.get(url)
    r.raise_for_status()
    return r.content
