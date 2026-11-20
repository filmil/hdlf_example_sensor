// SPDX-License-Identifier: Apache-2.0
//! Every registry crate of third_party/crates/Cargo.lock is in third_party/crates/crate_licences.txt, once,
//! at its version, and its licence expression offers a licence the project
//! accepts. The expression is SPDX: AND binds tighter than OR, parentheses
//! group, and "/" counts as OR, as old crates write it. An OR needs one
//! accepted side, an AND both. WITH and any word that is not an SPDX ID in
//! the accepted list make the expression unacceptable.
//!
//! Accepted: MIT, Apache-2.0, BSD-2-Clause, BSD-3-Clause and Zlib; and
//! Unicode-3.0 for unicode-ident only, a dependency of proc macros, which
//! run on the build machine and put nothing into the firmware.
use std::collections::BTreeMap;

const ACCEPTED: &[&str] = &["MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "Zlib"];
const ONLY_FOR: &[(&str, &str)] = &[("Unicode-3.0", "unicode-ident")];

fn read(var: &str) -> String {
    let path = std::env::var(var).unwrap_or_else(|_| panic!("{}", var));
    std::fs::read_to_string(&path).unwrap_or_else(|e| panic!("{}: {}", path, e))
}

fn tokens(expr: &str) -> Vec<String> {
    let spaced = expr.replace('(', " ( ").replace(')', " ) ").replace('/', " OR ");
    spaced.split_whitespace().map(str::to_string).collect()
}

/// A recursive-descent reader of an SPDX expression; each function says
/// whether what it read is acceptable for `krate`.
struct Reader<'a> {
    t: Vec<String>,
    i: usize,
    krate: &'a str,
}

impl Reader<'_> {
    fn peek(&self) -> Option<&str> {
        self.t.get(self.i).map(String::as_str)
    }
    fn or(&mut self) -> Result<bool, String> {
        let mut ok = self.and()?;
        while self.peek() == Some("OR") {
            self.i += 1;
            ok |= self.and()?;
        }
        Ok(ok)
    }
    fn and(&mut self) -> Result<bool, String> {
        let mut ok = self.atom()?;
        while self.peek() == Some("AND") {
            self.i += 1;
            ok &= self.atom()?;
        }
        Ok(ok)
    }
    fn atom(&mut self) -> Result<bool, String> {
        let tok = self.peek().ok_or("the expression ends early")?.to_string();
        self.i += 1;
        let ok = match tok.as_str() {
            "(" => {
                let ok = self.or()?;
                if self.peek() != Some(")") {
                    return Err("a ( with no )".into());
                }
                self.i += 1;
                ok
            }
            ")" | "AND" | "OR" | "WITH" => return Err(format!("{} where a licence belongs", tok)),
            id => ACCEPTED.contains(&id) || ONLY_FOR.iter().any(|&(l, k)| l == id && k == self.krate),
        };
        if self.peek() == Some("WITH") {
            return Err("WITH: an exception needs review".into());
        }
        Ok(ok)
    }
}

/// Whether `expr` offers an accepted licence for `krate`. An expression
/// that does not parse is not.
fn accepted(expr: &str, krate: &str) -> Result<bool, String> {
    let mut r = Reader { t: tokens(expr), i: 0, krate };
    let ok = r.or()?;
    if r.i != r.t.len() {
        return Err(format!("{:?} after the expression", r.t[r.i..].join(" ")));
    }
    Ok(ok)
}

/// The registry packages of a Cargo.lock, as (name, version).
fn locked() -> Vec<(String, String)> {
    let lock = read("CARGO_LOCK");
    let mut out = Vec::new();
    for block in lock.split("[[package]]").skip(1) {
        let field = |k: &str| {
            block
                .lines()
                .find_map(|l| l.strip_prefix(&format!("{} = \"", k)).map(|v| v.trim_end_matches('"').to_string()))
        };
        if field("source").is_some() {
            out.push((field("name").unwrap(), field("version").unwrap()));
        }
    }
    out
}

#[test]
fn every_locked_crate_has_an_accepted_licence() {
    let mut table = BTreeMap::new();
    let mut bad = Vec::new();
    for line in read("LICENCES").lines().filter(|l| !l.starts_with('#') && !l.trim().is_empty()) {
        let mut f = line.splitn(3, ' ');
        let (name, version, expr) = match (f.next(), f.next(), f.next()) {
            (Some(n), Some(v), Some(e)) if !e.trim().is_empty() => (n, v, e.trim()),
            _ => panic!("line {:?}: want name, version, licence", line),
        };
        if table.insert((name.to_string(), version.to_string()), expr.to_string()).is_some() {
            bad.push(format!("{} {}: listed twice", name, version));
        }
    }
    let lock = locked();
    assert!(!lock.is_empty(), "Cargo.lock has no registry packages");
    for k in &lock {
        match table.get(k).map(|e| (e, accepted(e, &k.0))) {
            None => bad.push(format!("{} {}: not in crate_licences.txt", k.0, k.1)),
            Some((e, Ok(false))) => bad.push(format!("{} {}: {} offers no accepted licence", k.0, k.1, e)),
            Some((e, Err(why))) => bad.push(format!("{} {}: {}: {}", k.0, k.1, e, why)),
            Some((_, Ok(true))) => {}
        }
    }
    for k in table.keys() {
        if !lock.contains(k) {
            bad.push(format!("{} {}: in crate_licences.txt but not in Cargo.lock", k.0, k.1));
        }
    }
    assert!(bad.is_empty(), "{}", bad.join("\n"));
    println!("{} crates, every one with an accepted licence", lock.len());
}

#[test]
fn the_rule() {
    let yes = |e: &str| assert_eq!(accepted(e, "some-crate"), Ok(true), "{}", e);
    let no = |e: &str| assert_eq!(accepted(e, "some-crate"), Ok(false), "{}", e);
    let error = |e: &str| assert!(accepted(e, "some-crate").is_err(), "{} parsed", e);
    yes("MIT");
    yes("MIT OR Apache-2.0");
    yes("Apache-2.0 / MIT");
    yes("MIT/Apache-2.0");
    yes("Unlicense OR MIT");
    yes("(GPL-3.0 AND MIT) OR Apache-2.0");
    yes("(MIT OR GPL-3.0) AND (Zlib OR GPL-3.0)");
    no("GPL-3.0");
    no("Unlicense");
    no("MIT AND GPL-3.0");
    no("GPL-3.0 OR LGPL-3.0 AND MIT"); // AND first: GPL-3.0 OR (LGPL-3.0 AND MIT)
    no("CONDOR-1.1");
    no("MITORApache-2.0");
    // Unicode-3.0 only for unicode-ident.
    no("(MIT OR Apache-2.0) AND Unicode-3.0");
    assert_eq!(accepted("(MIT OR Apache-2.0) AND Unicode-3.0", "unicode-ident"), Ok(true));
    error("MIT WITH LLVM-exception");
    error("MIT and GPL-3.0");
    error("MIT GPL-3.0");
    error("(MIT OR Apache-2.0");
    error("MIT OR");
    error("");
}
