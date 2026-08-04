check:
    scripts/validate-machine
    typos SKILL.md agents references scripts tests justfile

test: check
    ruby tests/machine_conformance.rb
