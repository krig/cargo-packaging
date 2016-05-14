# Cargo packaging tools for openSUSE

This repository contains a set of tools and rpm macros intended to
make it easy to package rust projects using the cargo package manager
for openSUSE.

The basic concept is this: Packaging a new crate should be as close as
possible to a one-liner:

        crate2opensuse my-crate 1.0.0

There's some things the tool might not be able to figure out such as
license, but in general this should then produce everything needed to
submit a new crate to `devel:languages:rust:crates`.

## Crates and RPM packages

The idea is to package crates as very light rpm wrappers around the
.crate archive. When installed, these are copied into
`/usr/lib/cargo/crates`, and a crate registry is maintained in
`/usr/lib/cargo/index`. When building a rust project, CARGO_HOME is
set to a directory containing `.cargo/config` with this content:

    [registry]
    index = "file:///usr/lib/cargo/index"

This way, cargo will go to the local index to find crates, rather than
to crates.io.

The way this is done practically is via the `cargo-packaging` rpm
which packages this repository, which also contains a series of rpm
macros. The `crate2opensuse` tool then edits the .spec file so that it
uses these macros, which make sure to unpack the crate in the right
location and update the index appropriately.

## The index

The index needs to be updated when crates are installed or
removed. This can be handled via pre/post hooks.

Each crate needs to install the crate itself, plus the metadata for
the registry:

    /usr/lib/cargo/crates/<crate-name>/<version>/download <- the crate itself
    /usr/lib/cargo/crates/<crate-name>/<version>/registry.json

The data in registry.json is fetched from crates.io when the crate
itself is (when creating the source rpm package).

The index data can then be inserted/removed by the registry
maintenance tool

/usr/lib/cargo/index/AA/BB/<crate-name>

Only the index data file for the crate in question needs to be
rebuilt when the crate is installed or removed.

## Version handling

If multiple versions of a crate should be available, then pass
--suffix "1" or --suffix "2_0" for example:

        crate2opensuse --suffix 2_0 my-crate 2.0.0

## Updating a crate

To update a crate when a new version is released, just use

        crate2opensuse --update my-crate

## cargo index format

Description here:

https://github.com/rust-lang/cargo/blob/master/src/cargo/sources/registry.rs

In the root of the index, there is `config.json`:

```
{
  "dl": "file:///usr/lib/cargo/crates",
  "api": ""
}
```

In `/usr/lib/cargo/index/<CR>/<AT>/<CRATE>` is something like:

```
{"name":"xapobase-sys","vers":"0.0.1","deps":[{"name":"winapi","req":"*","features":[""],"optional":false,"default_features":true,"target":null,"kind":"normal"}],"cksum":"bfbd4e02a10678d6365ce83e31c8cce41b58bd4f4cf63b92112f80fcc499b3ed","features":{},"yanked":false}
```



## Credits

* `cargo-bootstrap.py` by github/@dhuseby
* `golang-packaging` by github/@marguerite
* `cargo-vendor` by github/@alexcrichton
