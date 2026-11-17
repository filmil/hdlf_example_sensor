// SPDX-License-Identifier: Apache-2.0
//! Every crate in fw/Cargo.lock is in fw/crate_licences.txt, at the same
//! version, and its licence allows the firmware's use: each AND term has
//! an allowed OR alternative. Allowed: MIT, Apache-2.0, BSD-2-Clause,
//! BSD-3-Clause, Zlib; and Unicode-3.0, which unicode-ident, a build-time
//! dependency of proc macros, adds.
use std::collections::BTreeMap;

const ALLOWED: &[&str] = &["MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "Zlib", "Unicode-3.0"];

fn read(var: &str) -> String {
    let path = std::env::var(var).unwrap_or_else(|_| panic!("{}", var));
    std::fs::read_to_string(&path).unwrap_or_else(|e| panic!("{}: {}", path, e))
}

/// The registry packages of a Cargo.lock: name and version to nothing.
fn locked() -> BTreeMap<(String, String), ()> {
    let lock = read("CARGO_LOCK");
    let mut out = BTreeMap::new();
    for block in lock.split("[[package]]").skip(1) {
        let field = |k: &str| {
            block
                .lines()
                .find_map(|l| l.strip_prefix(&format!("{} = \"", k)).map(|v| v.trim_end_matches('"').to_string()))
        };
        if field("source").is_some() {
            out.insert((field("name").unwrap(), field("version").unwrap()), ());
        }
    }
    out
}

/// Whether an SPDX expression allows use: each AND term has an allowed
/// OR alternative ("/" counts as OR, as old crates write it).
fn allowed(expr: &str) -> bool {
    let e = expr.replace('(', "").replace(')', "");
    e.split("AND").all(|term| {
        term.split(|c| c == '/' || c == ' ')
            .flat_map(|t| t.split("OR"))
            .map(str::trim)
            .filter(|t| !t.is_empty())
            .any(|t| ALLOWED.contains(&t))
    })
}

#[test]
fn every_locked_crate_has_an_allowed_licence() {
    let table = read("LICENCES");
    let mut licences = BTreeMap::new();
    for line in table.lines().filter(|l| !l.starts_with('#') && !l.trim().is_empty()) {
        let f: Vec<&str> = line.split_whitespace().collect();
        assert_eq!(f.len(), 3, "line {:?}: want name, version, licence", line);
        licences.insert((f[0].to_string(), f[1].to_string()), f[2].to_string());
    }
    let lock = locked();
    assert!(!lock.is_empty(), "Cargo.lock has no registry packages");
    let mut bad = Vec::new();
    for (k, _) in &lock {
        match licences.get(k) {
            None => bad.push(format!("{} {}: not in crate_licences.txt", k.0, k.1)),
            Some(l) if !allowed(l) => bad.push(format!("{} {}: licence {} is not allowed", k.0, k.1, l)),
            _ => {}
        }
    }
    for k in licences.keys() {
        if !lock.contains_key(k) {
            bad.push(format!("{} {}: in crate_licences.txt but not in Cargo.lock", k.0, k.1));
        }
    }
    assert!(bad.is_empty(), "{}", bad.join("\n"));
    println!("{} crates, every licence allowed", lock.len());
}

#[test]
fn the_rule() {
    assert!(allowed("MIT"));
    assert!(allowed("MIT OR Apache-2.0"));
    assert!(allowed("MIT/Apache-2.0"));
    assert!(allowed("Unlicense OR MIT"));
    assert!(allowed("(MIT OR Apache-2.0) AND Unicode-3.0"));
    assert!(!allowed("GPL-3.0"));
    assert!(!allowed("MIT AND GPL-3.0"));
    assert!(!allowed("Unlicense"));
}
